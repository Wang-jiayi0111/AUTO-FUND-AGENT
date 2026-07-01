from __future__ import annotations

import argparse

from src.config import get_settings
from src.jobs.poll import process_blogger
from src.notify.wecom import WeComNotifier
from src.parse.pipeline import ParsePipeline
from src.store.feishu import FeishuStore
from src.store.seen import SeenStore
from src.utils.log_setup import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Reparse one article by URL")
    parser.add_argument("--url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()
    store = None if args.dry_run else FeishuStore(settings)
    total = 0
    for blogger in settings.bloggers:
        processed = process_blogger(
            blogger,
            ParsePipeline(settings),
            store,
            SeenStore(),
            WeComNotifier(settings.wecom_webhook_url),
            args.dry_run,
            limit=None,
            today_only=False,
            force_urls={args.url},
            only_urls={args.url},
        )
        total += processed
    if total == 0:
        raise SystemExit("Article URL was not found in configured RSS feeds.")
    print(f"Reparsed {total} article(s)")


if __name__ == "__main__":
    main()
