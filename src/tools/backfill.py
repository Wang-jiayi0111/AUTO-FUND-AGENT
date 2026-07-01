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
    parser = argparse.ArgumentParser(description="Backfill recent RSS articles")
    parser.add_argument("--blogger", required=True, help="Blogger id, e.g. lanjing")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()
    bloggers = {blogger.id: blogger for blogger in settings.bloggers}
    blogger = bloggers.get(args.blogger)
    if not blogger:
        raise SystemExit(f"Unknown blogger: {args.blogger}")

    store = None if args.dry_run else FeishuStore(settings)
    processed = process_blogger(
        blogger,
        ParsePipeline(settings),
        store,
        SeenStore(),
        WeComNotifier(settings.wecom_webhook_url),
        args.dry_run,
        limit=args.limit,
        today_only=False,
    )
    print(f"Backfill processed {processed} article(s)")


if __name__ == "__main__":
    main()
