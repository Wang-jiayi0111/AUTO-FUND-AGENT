from __future__ import annotations

import argparse
from pathlib import Path

from src.config import get_settings
from src.models import ArticleItem
from src.tools.manual_submit import (
    blogger_by_id,
    parse_published_at,
    submit_manual_article,
)
from src.utils.log_setup import configure_logging

MIN_CONTENT_CHARS = 80


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit article text manually when WeWe RSS or WeChat page fetch fails"
    )
    parser.add_argument("--blogger", required=True, help="blogger_id, e.g. lanjing")
    parser.add_argument("--url", required=True, help="Original WeChat article URL for dedupe/linking")
    parser.add_argument("--file", required=True, help="UTF-8 text file containing article content")
    parser.add_argument("--title", required=True, help="Article title")
    parser.add_argument(
        "--published-at",
        default="",
        help="Optional publish time: YYYY-MM-DD or ISO datetime; defaults to now",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing to Feishu")
    parser.add_argument("--force", action="store_true", help="Reparse existing final article")
    parser.add_argument(
        "--allow-short",
        action="store_true",
        help="Allow parsing even if article text is very short",
    )
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    configure_logging(log_file=args.log_file)
    settings = get_settings()
    blogger = blogger_by_id(settings.bloggers, args.blogger)
    text = Path(args.file).read_text(encoding="utf-8").strip()
    if not args.allow_short and len(text) < MIN_CONTENT_CHARS:
        raise SystemExit(
            f"Article text is too short ({len(text)} chars). "
            "Check the file content or re-run with --allow-short only if expected."
        )

    article = ArticleItem(
        blogger_id=blogger.id,
        blogger_name=blogger.name,
        title=args.title,
        url=args.url,
        guid=args.url,
        published_at=parse_published_at(args.published_at),
        content_html=text,
        content_text=text,
        image_urls=[],
    )
    print(submit_manual_article(settings, article, dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()
