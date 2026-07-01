"""Validate Feishu Bitable tables are reachable via Open API."""

from __future__ import annotations

import sys

from src.config import get_settings
from src.store.feishu import FeishuStore

TABLES = [
    ("bloggers", "Bloggers"),
    ("follow_list", "FollowList"),
    ("focus_list", "FocusList"),
    ("operations", "Operations"),
    ("articles", "Articles"),
    ("fund_mapping", "FundMapping"),
    ("pending_review", "PendingReview"),
]


def main() -> None:
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

    if failed:
        sys.exit(1)

    print("\nAll 7 Feishu tables validated.")
    print("\nRecord summary (first page, up to 100 rows):")
    for key, label in TABLES:
        try:
            count = len(store.list_records(key, page_size=100))
            print(f"  {label}: {count} row(s)")
        except Exception:  # noqa: BLE001
            pass

    follow = store.get_active_follow_bloggers()
    focus = store.get_active_focus_items()
    pending = store.get_pending_reviews()
    print(f"\nActive FollowList bloggers: {len(follow)} ({', '.join(sorted(follow)) or 'none'})")
    print(f"Active FocusList items: {len(focus)}")
    print(f"PendingReview (待确认): {len(pending)}")
    if not focus:
        print("  Tip: add FocusList rows in Feishu for priority digest alerts.")


if __name__ == "__main__":
    main()
