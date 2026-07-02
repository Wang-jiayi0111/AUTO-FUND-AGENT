from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from src.config import BloggerConfig
from src.models import ArticleItem

logger = logging.getLogger(__name__)

_IMG_RE = re.compile(r"https?://[^\s\"']+\.(?:jpg|jpeg|png|gif|webp)", re.I)
_WEWE_MIN_CONTENT_CHARS = 80
_CONTENT_NOENCODE_RE = re.compile(
    r"content_noencode:\s*['\"](.+?)['\"]\s*,\s*content",
    re.DOTALL,
)
_HTTP_HEADERS = {
    "User-Agent": "AUTO-FUND-AGENT/1.0",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _localhost_fallback_url(url: str) -> str | None:
    if "://localhost:" in url:
        return url.replace("://localhost:", "://127.0.0.1:", 1)
    return None


def _url_with_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _get_with_localhost_fallback(
    client: httpx.Client,
    url: str,
    **kwargs,
) -> httpx.Response:
    resp = client.get(url, **kwargs)
    fallback = _localhost_fallback_url(url)
    if fallback and resp.status_code >= 500:
        resp = client.get(fallback, **kwargs)
    return resp


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, IndexError):
        return None


def _extract_images(html: str, base_url: str = "") -> list[str]:
    urls: list[str] = []
    if html:
        soup = BeautifulSoup(html, "lxml")
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            if not src:
                continue
            full = urljoin(base_url, src)
            if full.startswith("http"):
                urls.append(full)
        for match in _IMG_RE.findall(html):
            urls.append(match)
    return list(dict.fromkeys(urls))


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _html_title(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for selector in (
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
    ):
        tag = soup.find(*selector)
        if tag and tag.get("content"):
            return str(tag.get("content", "")).strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    if soup.title:
        return soup.title.get_text(" ", strip=True)
    return ""


def looks_like_unavailable_wechat_page(html: str, url: str = "") -> bool:
    if "mp.weixin.qq.com" not in url and "mp.weixin.qq.com" not in html:
        return False
    markers = (
        "wappoc_appmsgcaptcha",
        "appmsgcaptcha",
        "环境异常",
        "验证码",
        "请在微信客户端打开",
        "当前环境异常",
    )
    return any(marker in html for marker in markers)


def _to_json_feed_url(feed_url: str) -> str | None:
    for suffix in (".rss", ".atom"):
        if feed_url.endswith(suffix):
            return feed_url[: -len(suffix)] + ".json"
    if feed_url.endswith(".json"):
        return feed_url
    return None


def _unescape_wewe_js_string(value: str) -> str:
    return (
        value.replace("\\x3c", "<")
        .replace("\\x3e", ">")
        .replace("\\x26", "&")
        .replace("\\x22", '"')
        .replace("\\x27", "'")
    )


def _extract_wewe_article_html(html: str) -> str:
    """WeWe fulltext may store the whole WeChat page; extract the article body."""
    if not html or len(html) < 100:
        return html
    soup = BeautifulSoup(html, "lxml")
    js_content = soup.find(id="js_content")
    if js_content is not None:
        text = js_content.get_text("\n", strip=True)
        if len(text) >= _WEWE_MIN_CONTENT_CHARS:
            return str(js_content)
    match = _CONTENT_NOENCODE_RE.search(html)
    if match:
        decoded = _unescape_wewe_js_string(match.group(1))
        if len(_html_to_text(decoded)) >= _WEWE_MIN_CONTENT_CHARS:
            return decoded
    return html


def _fetch_wewe_json_by_url(feed_url: str) -> dict[str, str]:
    json_url = _to_json_feed_url(feed_url)
    if not json_url:
        return {}
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = _get_with_localhost_fallback(client, json_url, headers=_HTTP_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}
    by_url: dict[str, str] = {}
    for item in data.get("items", []):
        url = item.get("url", "")
        if not url:
            continue
        body = _extract_wewe_article_html(item.get("content_html", ""))
        if body and len(_html_to_text(body)) >= _WEWE_MIN_CONTENT_CHARS:
            by_url[url] = body
    return by_url


def fetch_article_html(url: str, timeout: float = 20.0) -> str:
    if not url:
        return ""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = _get_with_localhost_fallback(client, url, headers=_HTTP_HEADERS)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError:
        return ""


def article_from_url(
    blogger: BloggerConfig,
    url: str,
    title: str = "",
    published_at: datetime | None = None,
) -> ArticleItem:
    html = fetch_article_html(url, timeout=60.0)
    body = _extract_wewe_article_html(html)
    text = _html_to_text(body)
    images = _extract_images(body, url)
    return ArticleItem(
        blogger_id=blogger.id,
        blogger_name=blogger.name,
        title=title or _html_title(html) or url,
        url=url,
        guid=url,
        published_at=published_at or datetime.now(tz=timezone.utc),
        content_html=body,
        content_text=text,
        image_urls=images,
    )


def _fetch_feed(feed_url: str) -> feedparser.FeedParserDict:
    """Fetch RSS with no-cache headers; fall back to feedparser's URL handling."""
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = _get_with_localhost_fallback(client, feed_url, headers=_HTTP_HEADERS)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
    except httpx.HTTPError:
        return feedparser.parse(feed_url)


def refresh_wewe_feed(feed_url: str) -> bool:
    """Ask WeWe RSS to refresh this feed before polling it."""
    if not feed_url:
        return False
    refresh_url = _url_with_query_param(feed_url, "update", "true")
    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = _get_with_localhost_fallback(client, refresh_url, headers=_HTTP_HEADERS)
            resp.raise_for_status()
        logger.info("WeWe RSS refresh requested: %s", refresh_url)
        return True
    except httpx.HTTPError as exc:
        logger.warning("WeWe RSS refresh failed: %s | %s", refresh_url, exc)
        return False


def enrich_article_images(article: ArticleItem) -> ArticleItem:
    if article.image_urls:
        return article
    html = fetch_article_html(article.url)
    if not html:
        return article
    images = _extract_images(html, article.url)
    text = article.content_text or _html_to_text(html)
    return ArticleItem(
        blogger_id=article.blogger_id,
        blogger_name=article.blogger_name,
        title=article.title,
        url=article.url,
        guid=article.guid,
        published_at=article.published_at,
        content_html=article.content_html or html,
        content_text=text,
        image_urls=images,
    )


def poll_rss(
    blogger: BloggerConfig,
    seen_guids: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[ArticleItem]:
    if not blogger.rss_url:
        return []
    seen = set(seen_guids or [])
    parsed = _fetch_feed(blogger.rss_url)
    wewe_html_by_url = _fetch_wewe_json_by_url(blogger.rss_url)
    articles: list[ArticleItem] = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("guid") or entry.get("link", "")
        if not guid or guid in seen:
            continue
        content = ""
        if entry.get("content"):
            content = entry.content[0].get("value", "")
        elif entry.get("summary"):
            content = entry.summary
        link = entry.get("link", "")
        if len(_html_to_text(content)) < _WEWE_MIN_CONTENT_CHARS and link in wewe_html_by_url:
            content = wewe_html_by_url[link]
        images = _extract_images(content, link)
        articles.append(
            ArticleItem(
                blogger_id=blogger.id,
                blogger_name=blogger.name,
                title=entry.get("title", ""),
                url=link,
                guid=guid,
                published_at=_parse_datetime(entry.get("published")),
                content_html=content,
                content_text=_html_to_text(content),
                image_urls=images,
            )
        )
    articles.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if limit:
        return articles[:limit]
    return articles
