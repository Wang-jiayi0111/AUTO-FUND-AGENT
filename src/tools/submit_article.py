from __future__ import annotations

import argparse

from src.config import get_settings
from src.ingest.rss_poller import (
    article_from_url,
    looks_like_unavailable_wechat_page,
)
from src.tools.manual_submit import (
    blogger_by_id,
    parse_published_at,
    submit_manual_article,
)
from src.utils.log_setup import configure_logging

MIN_CONTENT_CHARS = 80


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit one article URL manually when WeWe RSS misses it"
    )
    parser.add_argument("--blogger", required=True, help="blogger_id, e.g. lanjing")
    parser.add_argument("--url", required=True, help="WeChat article URL")
    parser.add_argument("--title", default="", help="Optional title override")
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
        help="Allow parsing even if fetched article text is very short",
    )
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    configure_logging(log_file=args.log_file)
    settings = get_settings()
    blogger = blogger_by_id(settings.bloggers, args.blogger)
    article = article_from_url(
        blogger,
        args.url,
        title=args.title,
        published_at=parse_published_at(args.published_at),
    )

    if looks_like_unavailable_wechat_page(article.content_html, article.url):
        raise SystemExit(
            "Fetched page looks like a WeChat captcha/unavailable page. "
            "Open the URL in a browser first; if only the browser can access it, copy the URL after it loads."
        )
    if not args.allow_short and len(article.content_text) < MIN_CONTENT_CHARS:
        raise SystemExit(
            f"Fetched article text is too short ({len(article.content_text)} chars). "
            "This usually means WeChat blocked the request. Re-run with --allow-short only if expected."
        )

    print(submit_manual_article(settings, article, dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()
