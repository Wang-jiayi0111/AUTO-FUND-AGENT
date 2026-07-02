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
    parser.add_argument("--blogger", help="Only scan one blogger id, e.g. tiantian")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()
    store = None if args.dry_run else FeishuStore(settings)
    bloggers = settings.bloggers
    if args.blogger:
        bloggers = [blogger for blogger in settings.bloggers if blogger.id == args.blogger]
        if not bloggers:
            known = ", ".join(blogger.id for blogger in settings.bloggers)
            raise SystemExit(f"Unknown blogger: {args.blogger}. Known bloggers: {known}")

    total = 0
    for blogger in bloggers:
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
            force_all=False,
        )
        total += processed
    if total == 0:
        if args.blogger:
            raise SystemExit(f"Article URL was not found in RSS feed for {args.blogger}.")
        raise SystemExit("Article URL was not found in configured RSS feeds.")
    print(f"Reparsed {total} article(s)")


if __name__ == "__main__":
    main()
