"""Validate Feishu Bitable tables are reachable via Open API."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

from src.config import get_settings
from src.store.feishu import FeishuStore

TABLES = [
    ("bloggers", "Bloggers"),
    ("focus_list", "FocusList"),
    ("operations", "Operations"),
    ("articles", "Articles"),
    ("fund_mapping", "FundMapping"),
    ("pending_review", "PendingReview"),
]

OPTIONAL_TABLES = [
    ("manual_submissions", "ManualSubmissions"),
]


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _first_blogger_record_id(store: FeishuStore) -> str:
    records = store.list_records("bloggers", page_size=1)
    if not records:
        raise RuntimeError("Bloggers table has no rows. Add at least one blogger before write-test.")
    return records[0]["record_id"]


def _write_test(store: FeishuStore) -> int:
    suffix = uuid.uuid4().hex[:8]
    blogger_record_id = _first_blogger_record_id(store)
    created: list[tuple[str, str]] = []
    failed = 0

    def create(label: str, table: str, fields: dict) -> str:
        nonlocal failed
        try:
            record_id = store.create_record(table, fields)
            created.append((table, record_id))
            print(f"OK: write {label} ({table})")
            return record_id
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL: write {label} ({table}) — {exc}")
            return ""

    print("\n=== Write test (no RSS/LLM) ===")
    article_id = create(
        "Articles",
        "articles",
        {
            "article_id": f"test-article-{suffix}",
            "blogger_id": [blogger_record_id],
            "guid": f"test-guid-{suffix}",
            "title": f"schema write test {suffix}",
            "article_url": {
                "link": f"https://example.com/auto-fund-agent/schema-test/{suffix}",
                "text": f"schema write test {suffix}",
            },
            "published_at": _now_ms(),
            "discovered_at": _now_ms(),
            "parsed_at": _now_ms(),
            "status": "待解析",
            "operation_count": 0,
            "pending_review_count": 0,
            "last_error": "",
            "raw_excerpt": "schema write test",
            "raw_json": "{}",
        },
    )

    operation_id = create(
        "Operations",
        "operations",
        {
            "op_id": f"test-op-{suffix}",
            "blogger_id": [blogger_record_id],
            "article_id": [article_id] if article_id else [],
            "article_guid": f"test-guid-{suffix}",
            "action": "观望",
            "fund_code": "",
            "fund_name": "半导体",
            "sector": "半导体",
            "amount_or_ratio": "",
            "reason": "schema write test",
            "confidence": 0.9,
            "article_url": {
                "link": f"https://example.com/auto-fund-agent/schema-test/{suffix}",
                "text": f"schema write test {suffix}",
            },
            "published_at": _now_ms(),
            "created_at": _now_ms(),
            "source": "manual",
            "status": "风险提示",
        },
    )

    create(
        "PendingReview",
        "pending_review",
        {
            "review_id": f"test-review-{suffix}",
            "raw_json": "{}",
            "blogger_id": [blogger_record_id],
            "article_id": [article_id] if article_id else [],
            "action": "买入",
            "fund_code": "000001",
            "fund_name": "华夏成长",
            "sector": "科技",
            "amount_or_ratio": "1万",
            "reason": "schema write test",
            "source": "manual",
            "code_candidates": "[]",
            "article_url": {
                "link": f"https://example.com/auto-fund-agent/schema-test/{suffix}",
                "text": f"schema write test {suffix}",
            },
            "published_at": _now_ms(),
            "confidence": 0.75,
            "processed_at": _now_ms(),
            "operation_id": [operation_id] if operation_id else [],
            "status": "待确认",
        },
    )

    create(
        "FundMapping",
        "fund_mapping",
        {
            "mapping_id": f"test-mapping-{suffix}",
            "blogger_id": [blogger_record_id],
            "fund_code": "000001",
            "fund_name": "华夏成长",
            "fund_name_raw": "华夏成长",
            "sector": "科技",
            "latest_action": "买入",
            "latest_op_id": [operation_id] if operation_id else [],
            "updated_at": _now_ms(),
        },
    )

    create(
        "FocusList",
        "focus_list",
        {
            "focus_id": f"test-focus-{suffix}",
            "blogger_id": [blogger_record_id],
            "fund_code": "000001",
            "fund_name": "华夏成长",
            "note": "schema write test",
            "active": True,
            "created_at": _now_ms(),
        },
    )

    if store.settings.feishu_tables.get("manual_submissions"):
        create(
            "ManualSubmissions",
            "manual_submissions",
            {
                "submission_id": f"test-submit-{suffix}",
                "blogger": "lanjing",
                "article_url": {
                    "link": f"https://example.com/auto-fund-agent/manual-submit/{suffix}",
                    "text": f"manual submit test {suffix}",
                },
                "title": f"manual submit test {suffix}",
                "article_text": "schema write test manual article text",
                "status": "待处理",
                "last_error": "",
                "processed_at": _now_ms(),
                "article_id": [article_id] if article_id else [],
                "created_at": _now_ms(),
            },
        )

    print("\nCleanup:")
    for table, record_id in reversed(created):
        try:
            store.delete_record(table, record_id)
            print(f"OK: delete {table} {record_id}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL: delete {table} {record_id} — {exc}")

    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Feishu Bitable setup")
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Create and delete test rows to validate field names/types without RSS or LLM",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_token:
        print("FAIL: Feishu not configured in .env")
        sys.exit(1)

    store = FeishuStore(settings)
    store._access_token()
    print("OK: tenant_access_token")

    failed = 0
    for key, label in TABLES:
        try:
            records = store.list_records(key, page_size=1)
            print(f"OK: {label} ({key}) — accessible ({len(records)} row(s) in first page)")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {label} ({key}) — {exc}")
            failed += 1

    for key, label in OPTIONAL_TABLES:
        if not settings.feishu_tables.get(key):
            print(f"SKIP: {label} ({key}) — optional table id not configured")
            continue
        try:
            records = store.list_records(key, page_size=1)
            print(f"OK: {label} ({key}) — accessible ({len(records)} row(s) in first page)")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {label} ({key}) — {exc}")
            failed += 1

    if failed:
        sys.exit(1)

    print("\nAll required Feishu tables validated.")
    print("\nRecord summary (first page, up to 100 rows):")
    for key, label in TABLES:
        try:
            count = len(store.list_records(key, page_size=100))
            print(f"  {label}: {count} row(s)")
        except Exception:  # noqa: BLE001
            pass

    active = store.get_active_blogger_ids()
    focus = store.get_active_focus_items()
    pending = store.get_pending_reviews()
    print(f"\nActive Bloggers: {len(active)} ({', '.join(sorted(active)) or 'none'})")
    print(f"Active FocusList items: {len(focus)}")
    print(f"PendingReview (待确认): {len(pending)}")
    if not focus:
        print("  Tip: add FocusList rows in Feishu for priority digest alerts.")

    if args.write_test:
        failed += _write_test(store)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
