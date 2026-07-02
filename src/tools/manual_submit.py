from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.config import BloggerConfig, Settings
from src.models import ArticleItem
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

logger = logging.getLogger(__name__)


def blogger_by_id(bloggers: list[BloggerConfig], blogger_id: str) -> BloggerConfig:
    for blogger in bloggers:
        if blogger.id == blogger_id:
            return blogger
    known = ", ".join(blogger.id for blogger in bloggers)
    raise SystemExit(f"Unknown blogger: {blogger_id}. Known bloggers: {known}")


def blogger_by_text(bloggers: list[BloggerConfig], text: str) -> BloggerConfig:
    value = text.strip()
    for blogger in bloggers:
        if value in {
            getattr(blogger, "id", ""),
            getattr(blogger, "name", ""),
            getattr(blogger, "wechat_name", ""),
        }:
            return blogger
    known = ", ".join(f"{blogger.id}/{blogger.name}" for blogger in bloggers)
    raise ValueError(f"Unknown blogger: {text}. Known bloggers: {known}")


def parse_published_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError as exc:
        raise SystemExit("Invalid --published-at. Use YYYY-MM-DD or ISO datetime.") from exc


def article_should_skip(store: FeishuStore, record: dict | None) -> bool:
    if not record:
        return False
    status = store._field_text(record, "status")
    return status in FINAL_ARTICLE_STATUSES or status == ARTICLE_STATUS_FAILED


def print_dry_run(article: ArticleItem, result, pipeline: ParsePipeline) -> None:
    trade_ops = [op for op in result.operations if not pipeline.is_sector_alert(op)]
    risk_ops = [op for op in result.operations if pipeline.is_sector_alert(op)]
    print(json.dumps(
        {
            "blogger": article.blogger_name,
            "title": article.title,
            "url": article.url,
            "content_chars": len(article.content_text),
            "image_count": len(article.image_urls),
            "operations": [
                {
                    "action": op.action,
                    "fund_code": op.fund_code,
                    "fund_name": op.fund_name,
                    "sector": op.sector,
                    "amount_or_ratio": op.amount_or_ratio,
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


def submit_manual_article(
    settings: Settings,
    article: ArticleItem,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    store = None if dry_run else FeishuStore(settings)
    pipeline = ParsePipeline(settings)
    notifier = WeComNotifier(settings.wecom_webhook_url)

    article_record_id: str | None = None
    if store:
        existing = store.find_article(article.guid, article.url)
        if not force and article_should_skip(store, existing):
            logger.info(
                "Skip existing article: %s | %s | status=%s",
                article.blogger_name,
                article.title,
                store._field_text(existing or {}, "status"),
            )
            return "Article already processed. Use --force to reparse."
        if existing:
            article_record_id = existing["record_id"]
        else:
            article_record_id = store.create_article(article)
        store.mark_article_parsing(article_record_id)

    logger.info("Manual article submit: %s | %s", article.blogger_name, article.title)
    try:
        result = pipeline.parse_article(article)
    except Exception as exc:  # noqa: BLE001
        if store and article_record_id:
            store.mark_article_failed(article_record_id, str(exc))
        raise

    if dry_run:
        print_dry_run(article, result, pipeline)
        return "Dry run complete."

    if not store or not article_record_id:
        raise SystemExit("Feishu is not configured.")

    if not result.operations:
        logger.info("No operations parsed for: %s", article.title)
        store.mark_article_done(article_record_id, ARTICLE_STATUS_NO_OPS, 0, 0, result.raw_json)
        return "Submitted article, no operations parsed."

    review_raw_saved = False
    saved_sector_alerts = []
    operation_count = 0
    pending_count = 0
    for op in result.operations:
        if pipeline.should_auto_store(op):
            store.save_operation(article, op, article_record_id=article_record_id, source="manual")
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
                f"**待确认操作**\n博主：{article.blogger_name}\n基金：{op.fund_name}\n"
                f"置信度：{op.confidence:.0%}\n[打开飞书确认]({link})"
            )
        else:
            notifier.send_text(
                f"需人工查看：{article.blogger_name} | {article.title} | {article.url}"
            )

    if saved_sector_alerts:
        notifier.send_markdown(
            format_sector_risk_markdown(article.blogger_name, article, saved_sector_alerts)
        )

    status = ARTICLE_STATUS_REVIEW if pending_count else ARTICLE_STATUS_PARSED
    store.mark_article_done(
        article_record_id,
        status,
        operation_count,
        pending_count,
        result.raw_json,
    )
    return (
        "Submitted article: "
        f"operations={operation_count}, pending_reviews={pending_count}, status={status}"
    )
