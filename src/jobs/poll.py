from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from src.config import get_settings
from src.ingest.rss_poller import poll_rss, refresh_wewe_feed
from src.notify.messages import format_sector_risk_markdown
from src.notify.wecom import WeComNotifier
from src.parse.pipeline import ParsePipeline
from src.store.feishu import (
    ARTICLE_STATUS_FAILED,
    ARTICLE_STATUS_NO_OPS,
    ARTICLE_STATUS_PARSED,
    ARTICLE_STATUS_REVIEW,
    FINAL_ARTICLE_STATUSES,
    FeishuStore,
)
from src.store.seen import SeenStore
from src.utils.log_setup import configure_logging

logger = logging.getLogger(__name__)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class PollStats:
    found: int = 0
    skipped: int = 0
    processed: int = 0
    auto_saved: int = 0
    pending: int = 0
    failed: int = 0


def _is_today_article(article) -> bool:
    if article.published_at:
        dt = article.published_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SHANGHAI_TZ).date() == datetime.now(SHANGHAI_TZ).date()
    return True


def _article_should_skip(record: dict | None) -> bool:
    if not record:
        return False
    status = FeishuStore._field_text(record, "status")
    return status in FINAL_ARTICLE_STATUSES or status == ARTICLE_STATUS_FAILED


def process_blogger(
    blogger,
    pipeline: ParsePipeline,
    store: FeishuStore | None,
    seen: SeenStore,
    notifier: WeComNotifier,
    dry_run: bool,
    limit: int | None = None,
    today_only: bool = True,
    force_urls: set[str] | None = None,
    only_urls: set[str] | None = None,
    force_all: bool = False,
    refresh_rss: bool = False,
    refresh_wait_seconds: float = 0.0,
) -> int:
    known = seen.seen_for_blogger(blogger.id) if not store else set()
    try:
        if refresh_rss:
            refresh_wewe_feed(blogger.rss_url)
            if refresh_wait_seconds > 0:
                time.sleep(refresh_wait_seconds)
        articles = poll_rss(blogger, known, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.error("RSS poll failed for %s: %s", blogger.id, exc)
        if store:
            try:
                store.update_blogger_health(blogger.id, success=False, error=str(exc))
            except Exception as health_exc:  # noqa: BLE001
                logger.warning("Failed to update blogger health for %s: %s", blogger.id, health_exc)
        return 0
    stats = PollStats(found=len(articles))

    if store:
        try:
            store.update_blogger_health(
                blogger.id,
                success=True,
                article=articles[0] if articles else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to update blogger health for %s: %s", blogger.id, exc)

    for article in articles:
        if only_urls is not None and article.url not in only_urls:
            continue
        force = force_all or article.url in (force_urls or set())
        if today_only and not force and not _is_today_article(article):
            logger.info("Skip non-today article: %s | %s", blogger.name, article.title)
            stats.skipped += 1
            continue

        article_record_id: str | None = None
        if store:
            existing = store.find_article(article.guid, article.url)
            if not force and _article_should_skip(existing):
                logger.info(
                    "Skip existing article: %s | %s | status=%s",
                    blogger.name,
                    article.title,
                    FeishuStore._field_text(existing or {}, "status"),
                )
                stats.skipped += 1
                continue
            if existing:
                article_record_id = existing["record_id"]
            else:
                article_record_id = store.create_article(article)

        logger.info("New article: %s | %s", blogger.name, article.title)
        try:
            if store and article_record_id:
                store.mark_article_parsing(article_record_id)
            result = pipeline.parse_article(article)
        except (httpx.HTTPError, Exception) as exc:  # noqa: BLE001
            logger.error(
                "Parse failed for %s | %s: %s",
                blogger.name,
                article.title,
                exc,
            )
            if store and article_record_id:
                store.mark_article_failed(article_record_id, str(exc))
            stats.failed += 1
            continue

        if dry_run:
            trade_ops = [op for op in result.operations if not pipeline.is_sector_alert(op)]
            risk_ops = [op for op in result.operations if pipeline.is_sector_alert(op)]
            print(json.dumps(
                {
                    "blogger": blogger.name,
                    "title": article.title,
                    "url": article.url,
                    "operations": [
                        {
                            "action": op.action,
                            "fund_code": op.fund_code,
                            "fund_name": op.fund_name,
                            "sector": op.sector,
                            "reason": op.reason,
                            "confidence": op.confidence,
                            "candidates": len(op.code_candidates),
                        }
                        for op in trade_ops
                    ],
                    "sector_risk_alerts": [
                        {
                            "sector": op.sector,
                            "reason": op.reason,
                            "amount_or_ratio": op.amount_or_ratio,
                        }
                        for op in risk_ops
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ))
            seen.mark_seen(blogger.id, article.guid)
            stats.processed += 1
            continue

        if not store:
            logger.warning("Feishu not configured, skipping store")
            seen.mark_seen(blogger.id, article.guid)
            stats.processed += 1
            continue

        if not result.operations:
            logger.info("No operations parsed for: %s", article.title)
            if article_record_id:
                store.mark_article_done(article_record_id, ARTICLE_STATUS_NO_OPS, 0, 0, result.raw_json)
            seen.mark_seen(blogger.id, article.guid)
            stats.processed += 1
            continue

        review_raw_saved = False
        saved_sector_alerts: list = []
        operation_count = 0
        pending_count = 0
        for op in result.operations:
            if pipeline.should_auto_store(op):
                store.save_operation(article, op, article_record_id=article_record_id)
                operation_count += 1
            elif pipeline.should_save_sector_alert(op):
                store.save_sector_alert(article, op, article_record_id=article_record_id)
                saved_sector_alerts.append(op)
                operation_count += 1
            elif pipeline.should_review(op):
                raw_payload = result.raw_json if not review_raw_saved else {}
                review_id = store.save_pending_review(
                    article,
                    op,
                    raw_payload,
                    article_record_id=article_record_id,
                )
                review_raw_saved = True
                pending_count += 1
                link = store.record_link("pending_review", review_id)
                notifier.send_markdown(
                    f"**待确认操作**\n博主：{blogger.name}\n基金：{op.fund_name}\n"
                    f"置信度：{op.confidence:.0%}\n[打开飞书确认]({link})"
                )
            else:
                notifier.send_text(
                    f"需人工查看：{blogger.name} | {article.title} | {article.url}"
                )

        if saved_sector_alerts:
            notifier.send_markdown(
                format_sector_risk_markdown(blogger.name, article, saved_sector_alerts)
            )

        if article_record_id:
            status = ARTICLE_STATUS_REVIEW if pending_count else ARTICLE_STATUS_PARSED
            store.mark_article_done(
                article_record_id,
                status,
                operation_count,
                pending_count,
                result.raw_json,
            )

        seen.mark_seen(blogger.id, article.guid)
        stats.processed += 1
        stats.auto_saved += operation_count
        stats.pending += pending_count

    logger.info(
        "Blogger stats %s: found=%s skipped=%s processed=%s saved=%s pending=%s failed=%s",
        blogger.id,
        stats.found,
        stats.skipped,
        stats.processed,
        stats.auto_saved,
        stats.pending,
        stats.failed,
    )
    return stats.processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll RSS feeds and parse fund operations")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing to Feishu")
    parser.add_argument("--limit", type=int, default=None, help="Max new articles per blogger")
    parser.add_argument("--blogger", type=str, default=None, help="Only process one blogger_id")
    parser.add_argument("--include-old", action="store_true", help="Process non-today articles")
    parser.add_argument("--force", action="store_true", help="Reparse existing Articles rows")
    parser.add_argument(
        "--refresh-rss",
        action="store_true",
        help="Request WeWe RSS refresh with ?update=true before reading each feed",
    )
    parser.add_argument(
        "--refresh-wait-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait after each WeWe RSS refresh request",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Append logs to this UTF-8 file (do not use shell >> redirect)",
    )
    args = parser.parse_args()

    configure_logging(log_file=args.log_file)

    settings = get_settings()
    pipeline = ParsePipeline(settings)
    seen = SeenStore()
    notifier = WeComNotifier(settings.wecom_webhook_url)

    store = None
    if not args.dry_run and settings.feishu_app_id and settings.feishu_app_token:
        store = FeishuStore(settings)
    active_blogger_ids = store.get_active_blogger_ids() if store else {b.id for b in settings.bloggers}
    if store and not active_blogger_ids:
        logger.warning("No active Bloggers found by status; skip all bloggers")

    total = 0
    for blogger in settings.bloggers:
        if args.blogger and blogger.id != args.blogger:
            continue
        if blogger.id not in active_blogger_ids:
            logger.info("Skip disabled blogger %s", blogger.id)
            continue
        if not blogger.rss_url:
            logger.warning("Missing RSS URL for blogger %s", blogger.id)
            continue
        total += process_blogger(
            blogger,
            pipeline,
            store,
            seen,
            notifier,
            args.dry_run,
            limit=args.limit,
            today_only=not args.include_old,
            force_all=args.force,
            refresh_rss=args.refresh_rss,
            refresh_wait_seconds=args.refresh_wait_seconds,
        )

    logger.info("Processed %s new article(s)", total)


if __name__ == "__main__":
    main()
