from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from src.config import get_settings
from src.ingest.rss_poller import article_from_url, looks_like_unavailable_wechat_page
from src.models import ArticleItem
from src.store.feishu import FeishuStore
from src.tools.manual_submit import (
    blogger_by_text,
    parse_published_at,
    submit_manual_article,
)
from src.utils.log_setup import configure_logging

logger = logging.getLogger(__name__)
MIN_CONTENT_CHARS = 80

STATUS_PENDING = "待处理"
STATUS_PROCESSING = "处理中"
STATUS_DONE = "已处理"
STATUS_FAILED = "处理失败"
PENDING_STATUSES = {"", STATUS_PENDING}


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _table_configured(store: FeishuStore) -> bool:
    return bool(store.settings.feishu_tables.get("manual_submissions", ""))


def _field_text(store: FeishuStore, rec: dict, *keys: str) -> str:
    for key in keys:
        value = store._field_text(rec, key)
        if value:
            return value
    return ""


def _field_url(store: FeishuStore, rec: dict, *keys: str) -> str:
    for key in keys:
        value = store._field_url(rec, key)
        if value:
            return value
    return ""


def _article_from_submission(settings, store: FeishuStore, rec: dict) -> ArticleItem:
    blogger_text = _field_text(store, rec, "blogger", "blogger_id", "blogger_name")
    if not blogger_text:
        raise ValueError("Missing blogger")
    blogger = blogger_by_text(settings.bloggers, blogger_text)
    url = _field_url(store, rec, "article_url", "url")
    if not url:
        raise ValueError("Missing article_url")
    title = _field_text(store, rec, "title")
    published_ms = store._field_number(rec, "published_at")
    published = (
        datetime.fromtimestamp(float(published_ms) / 1000, tz=timezone.utc)
        if published_ms is not None
        else parse_published_at(_field_text(store, rec, "published_at"))
    )
    article_text = _field_text(store, rec, "article_text", "content_text")
    if article_text:
        return ArticleItem(
            blogger_id=blogger.id,
            blogger_name=blogger.name,
            title=title or url,
            url=url,
            guid=url,
            published_at=published,
            content_html=article_text,
            content_text=article_text,
            image_urls=[],
        )
    article = article_from_url(blogger, url, title=title, published_at=published)
    if looks_like_unavailable_wechat_page(article.content_html, article.url):
        raise ValueError("Fetched page looks like a WeChat captcha/unavailable page")
    if len(article.content_text) < MIN_CONTENT_CHARS:
        raise ValueError(
            f"Fetched article text is too short ({len(article.content_text)} chars); "
            "fill article_text in ManualSubmissions as a fallback"
        )
    return article


def _pending_submissions(store: FeishuStore) -> list[dict]:
    records = store.list_records("manual_submissions")
    return [
        rec for rec in records
        if store._field_text(rec, "status") in PENDING_STATUSES
    ]


def process_submissions(*, dry_run: bool = False, limit: int | None = None) -> tuple[int, int]:
    settings = get_settings()
    store = FeishuStore(settings)
    if not _table_configured(store):
        logger.info("ManualSubmissions table is not configured; skip")
        return 0, 0

    processed = 0
    failed = 0
    submissions = _pending_submissions(store)
    if limit:
        submissions = submissions[:limit]

    for rec in submissions:
        record_id = rec["record_id"]
        try:
            article = _article_from_submission(settings, store, rec)
            logger.info("Manual submission: %s | %s", article.blogger_name, article.url)
            if dry_run:
                print(f"DRY-RUN {article.blogger_name} | {article.title} | {article.url}")
                processed += 1
                continue

            store.update_record(
                "manual_submissions",
                record_id,
                {"status": STATUS_PROCESSING, "last_error": ""},
            )
            message = submit_manual_article(settings, article, dry_run=False, force=False)
            article_record = store.find_article(article.guid, article.url)
            fields = {
                "status": STATUS_DONE,
                "processed_at": _now_ms(),
                "last_error": "",
            }
            if article_record:
                fields["article_id"] = [article_record["record_id"]]
            store.update_record("manual_submissions", record_id, fields)
            logger.info("Manual submission processed: %s", message)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Manual submission failed: %s", exc)
            failed += 1
            if not dry_run:
                store.update_record(
                    "manual_submissions",
                    record_id,
                    {
                        "status": STATUS_FAILED,
                        "processed_at": _now_ms(),
                        "last_error": str(exc)[:2000],
                    },
                )

    return processed, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply pending manual article submissions from Feishu")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    configure_logging(log_file=args.log_file)
    processed, failed = process_submissions(dry_run=args.dry_run, limit=args.limit)
    print(f"Manual submissions: processed={processed}, failed={failed}")


if __name__ == "__main__":
    main()
