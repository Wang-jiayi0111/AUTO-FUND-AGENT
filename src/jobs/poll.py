from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.ingest.rss_poller import poll_rss
from src.notify.wecom import WeComNotifier
from src.parse.pipeline import ParsePipeline
from src.store.feishu import FeishuStore
from src.store.seen import SeenStore
from src.utils.log_setup import configure_logging

logger = logging.getLogger(__name__)


def process_blogger(
    blogger,
    pipeline: ParsePipeline,
    store: FeishuStore | None,
    seen: SeenStore,
    notifier: WeComNotifier,
    dry_run: bool,
    limit: int | None = None,
) -> int:
    known = seen.seen_for_blogger(blogger.id)
    articles = poll_rss(blogger, known, limit=limit)
    processed = 0

    for article in articles:
        logger.info("New article: %s | %s", blogger.name, article.title)
        result = pipeline.parse_article(article)

        if dry_run:
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
                            "confidence": op.confidence,
                            "candidates": len(op.code_candidates),
                        }
                        for op in result.operations
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ))
            seen.mark_seen(blogger.id, article.guid)
            processed += 1
            continue

        if not store:
            logger.warning("Feishu not configured, skipping store")
            seen.mark_seen(blogger.id, article.guid)
            continue

        if not result.operations:
            logger.info("No operations parsed for: %s", article.title)
            seen.mark_seen(blogger.id, article.guid)
            continue

        review_raw_saved = False
        for op in result.operations:
            if pipeline.should_auto_store(op):
                store.save_operation(article, op)
            elif pipeline.should_save_sector_alert(op):
                store.save_sector_alert(article, op)
                notifier.send_markdown(
                    f"**⚠️ 板块风险提示**\n博主：{blogger.name}\n"
                    f"板块：{op.sector}\n"
                    f"观点：{op.reason or op.amount_or_ratio}\n"
                    f"[查看原文]({article.url})"
                )
            elif pipeline.should_review(op):
                raw_payload = result.raw_json if not review_raw_saved else {}
                review_id = store.save_pending_review(article, op, raw_payload)
                review_raw_saved = True
                link = store.record_link("pending_review", review_id)
                notifier.send_markdown(
                    f"**待确认操作**\n博主：{blogger.name}\n基金：{op.fund_name}\n"
                    f"置信度：{op.confidence:.0%}\n[打开飞书确认]({link})"
                )
            else:
                notifier.send_text(
                    f"需人工查看：{blogger.name} | {article.title} | {article.url}"
                )

        seen.mark_seen(blogger.id, article.guid)
        processed += 1

    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll RSS feeds and parse fund operations")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing to Feishu")
    parser.add_argument("--limit", type=int, default=None, help="Max new articles per blogger")
    parser.add_argument("--blogger", type=str, default=None, help="Only process one blogger_id")
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

    total = 0
    for blogger in settings.bloggers:
        if args.blogger and blogger.id != args.blogger:
            continue
        if not blogger.rss_url:
            logger.warning("Missing RSS URL for blogger %s", blogger.id)
            continue
        total += process_blogger(
            blogger, pipeline, store, seen, notifier, args.dry_run, limit=args.limit
        )

    logger.info("Processed %s new article(s)", total)


if __name__ == "__main__":
    main()
