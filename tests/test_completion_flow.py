import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.jobs.poll import process_blogger
from src.models import ArticleItem, ParsedOperation, ParseResult
from src.store.feishu import FeishuStore


class Blogger:
    id = "lanjing"
    name = "蓝鲸跃财"
    rss_url = "http://rss.local/feed.rss"


class FakePipeline:
    def __init__(self):
        self.calls = 0

    def parse_article(self, article):
        self.calls += 1
        op = ParsedOperation(
            action="买入",
            fund_code="000001",
            fund_name="华夏成长",
            fund_name_raw="华夏成长",
            fund_code_source="ocr",
            sector="科技",
            amount_or_ratio="1万",
            reason="测试",
            confidence=0.95,
            source="text",
        )
        return ParseResult(article=article, operations=[op], raw_json={"ok": True})

    def should_auto_store(self, op):
        return True

    def should_save_sector_alert(self, op):
        return False

    def should_review(self, op):
        return False

    def is_sector_alert(self, op):
        return False


class FakeStore:
    def __init__(self):
        self.articles_by_url = {}
        self.saved_ops = []
        self.done = []

    def update_blogger_health(self, *args, **kwargs):
        return None

    def find_article(self, guid, url):
        return self.articles_by_url.get(url)

    def create_article(self, article):
        rec = {"record_id": "art1", "fields": {"status": "待解析", "article_url": {"link": article.url}}}
        self.articles_by_url[article.url] = rec
        return "art1"

    def mark_article_parsing(self, record_id):
        for rec in self.articles_by_url.values():
            if rec["record_id"] == record_id:
                rec["fields"]["status"] = "解析中"

    def mark_article_done(self, record_id, status, operation_count, pending_review_count, raw_json=None):
        self.done.append((record_id, status, operation_count, pending_review_count))
        for rec in self.articles_by_url.values():
            if rec["record_id"] == record_id:
                rec["fields"]["status"] = status

    def mark_article_failed(self, record_id, error):
        for rec in self.articles_by_url.values():
            if rec["record_id"] == record_id:
                rec["fields"]["status"] = "解析失败"

    def save_operation(self, article, op, status="自动入库", article_record_id=None, source=None):
        self.saved_ops.append((article.url, op.fund_code, article_record_id))
        return "op1"


class FakeSeen:
    def seen_for_blogger(self, blogger_id):
        return set()

    def mark_seen(self, blogger_id, guid):
        return None


class FakeNotifier:
    def send_markdown(self, text):
        return None

    def send_text(self, text):
        return None


def article(title="today", published_at=None, url="http://example.com/a"):
    return ArticleItem(
        blogger_id="lanjing",
        blogger_name="蓝鲸跃财",
        title=title,
        url=url,
        guid=url,
        published_at=published_at or datetime.now(tz=timezone.utc),
        content_html="<p>text</p>",
        content_text="text",
        image_urls=[],
    )


class CompletionFlowTests(unittest.TestCase):
    def test_field_url_prefers_link_over_text(self):
        record = {"fields": {"article_url": {"link": "http://example.com/a", "text": "标题"}}}
        self.assertEqual(FeishuStore._field_url(record, "article_url"), "http://example.com/a")

    def test_poll_skips_non_today_articles(self):
        old_article = article(
            title="old",
            published_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
            url="http://example.com/old",
        )
        pipeline = FakePipeline()
        with patch("src.jobs.poll.poll_rss", return_value=[old_article]):
            processed = process_blogger(
                Blogger(),
                pipeline,
                FakeStore(),
                FakeSeen(),
                FakeNotifier(),
                dry_run=False,
                limit=5,
            )
        self.assertEqual(processed, 0)
        self.assertEqual(pipeline.calls, 0)

    def test_repeated_poll_does_not_reparse_final_article(self):
        today_article = article()
        store = FakeStore()
        pipeline = FakePipeline()
        with patch("src.jobs.poll.poll_rss", return_value=[today_article]):
            first = process_blogger(
                Blogger(), pipeline, store, FakeSeen(), FakeNotifier(), False, limit=5
            )
            second = process_blogger(
                Blogger(), pipeline, store, FakeSeen(), FakeNotifier(), False, limit=5
            )
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(pipeline.calls, 1)
        self.assertEqual(len(store.saved_ops), 1)
        self.assertEqual(store.done[0][1], "已解析")


if __name__ == "__main__":
    unittest.main()
