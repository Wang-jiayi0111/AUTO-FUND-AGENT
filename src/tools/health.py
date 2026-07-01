from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.config import get_settings
from src.ingest.rss_poller import poll_rss
from src.store.feishu import ARTICLE_STATUS_FAILED, FeishuStore

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def main() -> None:
    settings = get_settings()
    store = FeishuStore(settings)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    print("=== RSS ===")
    for blogger in settings.bloggers:
        if not blogger.rss_url:
            print(f"[FAIL] {blogger.name}: missing RSS URL")
            continue
        try:
            articles = poll_rss(blogger, seen_guids=[], limit=1)
            if articles:
                article = articles[0]
                published = article.published_at.astimezone(SHANGHAI_TZ).strftime(
                    "%Y-%m-%d %H:%M"
                ) if article.published_at else "unknown"
                print(f"[OK] {blogger.name}: {published} | {article.title}")
            else:
                print(f"[WARN] {blogger.name}: RSS reachable but empty")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {blogger.name}: {exc}")

    print("\n=== Feishu Articles (24h) ===")
    try:
        articles = store.get_articles_since(since)
        failed = [a for a in articles if store._field_text(a, "status") == ARTICLE_STATUS_FAILED]
        pending = store.get_pending_reviews()
        print(f"Articles: {len(articles)}")
        print(f"Failed: {len(failed)}")
        print(f"PendingReview: {len(pending)}")
        if failed:
            for item in failed[:5]:
                print(f"- FAILED: {store._field_text(item, 'title')} | {store._field_text(item, 'last_error')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Feishu articles: {exc}")


if __name__ == "__main__":
    main()
