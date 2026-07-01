from __future__ import annotations

import argparse
from datetime import datetime, timezone

from src.config import get_settings
from src.models import ArticleItem, ParsedOperation
from src.store.feishu import ARTICLE_STATUS_IGNORED, ARTICLE_STATUS_PARSED, FeishuStore


def _to_float(value: str, default: float = 0.7) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dt_from_ms(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)


def _article_from_review(store: FeishuStore, review: dict) -> ArticleItem:
    blogger_id = store.blogger_id_from_field(review, "blogger_id")
    url = store._field_url(review, "article_url")
    title = store._field_text(review, "article_url") or url
    published = _dt_from_ms(store._field_number(review, "published_at"))
    return ArticleItem(
        blogger_id=blogger_id,
        blogger_name=blogger_id,
        title=title,
        url=url,
        guid=url,
        published_at=published,
        content_html="",
        content_text="",
        image_urls=[],
    )


def _operation_from_review(store: FeishuStore, review: dict) -> ParsedOperation:
    return ParsedOperation(
        action=store._field_text(review, "action") or "买入",
        fund_code=store._field_text(review, "fund_code"),
        fund_name=store._field_text(review, "fund_name"),
        fund_name_raw=store._field_text(review, "fund_name"),
        fund_code_source="manual",
        sector=store._field_text(review, "sector"),
        amount_or_ratio=store._field_text(review, "amount_or_ratio"),
        reason=store._field_text(review, "reason"),
        confidence=_to_float(store._field_text(review, "confidence"), default=1.0),
        source="manual",
        code_candidates=[],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply approved Feishu pending reviews")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    store = FeishuStore(get_settings())
    reviews = store.get_reviews_to_apply()
    created = 0
    rejected = 0

    for review in reviews:
        status = store._field_text(review, "status")
        article_record_id = store.article_record_id_from_field(review)
        if status == "已通过":
            article = _article_from_review(store, review)
            op = _operation_from_review(store, review)
            print(f"APPROVE: {article.blogger_id} | {op.action} | {op.fund_name}")
            if not args.dry_run:
                operation_id = store.save_operation(
                    article,
                    op,
                    status="已确认",
                    article_record_id=article_record_id or None,
                    source="manual",
                )
                store.update_record(
                    "pending_review",
                    review["record_id"],
                    {
                        "status": "已处理",
                        "processed_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
                        "operation_id": [operation_id],
                    },
                )
                if article_record_id:
                    store.mark_article_done(article_record_id, ARTICLE_STATUS_PARSED, 1, 0)
            created += 1
        elif status == "已拒绝":
            print(f"REJECT: {store._field_text(review, 'fund_name')}")
            if not args.dry_run:
                store.update_record(
                    "pending_review",
                    review["record_id"],
                    {
                        "status": "已处理",
                        "processed_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
                    },
                )
                if article_record_id:
                    store.update_article(article_record_id, {"status": ARTICLE_STATUS_IGNORED})
            rejected += 1

    action = "Would apply" if args.dry_run else "Applied"
    print(f"{action}: approved={created}, rejected={rejected}")


if __name__ == "__main__":
    main()
