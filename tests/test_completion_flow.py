import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.ingest.rss_poller import (
    _html_title,
    _url_with_query_param,
    looks_like_unavailable_wechat_page,
)
from src.jobs.digest import _source_status
from src.jobs.poll import process_blogger
from src.models import ArticleItem, ParsedOperation, ParseResult
from src.store.feishu import FeishuStore
from src.tools.apply_manual_submissions import _article_from_submission
from src.tools.manual_submit import blogger_by_text


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
        self.health_updates = []

    def update_blogger_health(self, *args, **kwargs):
        self.health_updates.append((args, kwargs))
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


class Settings:
    bloggers = [Blogger()]


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

    def test_wewe_refresh_url_adds_update_true(self):
        url = _url_with_query_param("http://localhost:4000/feeds/a.rss", "update", "true")
        self.assertEqual(url, "http://localhost:4000/feeds/a.rss?update=true")

    def test_wewe_refresh_url_preserves_existing_query(self):
        url = _url_with_query_param("http://localhost:4000/feeds/a.rss?foo=bar", "update", "true")
        self.assertEqual(url, "http://localhost:4000/feeds/a.rss?foo=bar&update=true")

    def test_html_title_prefers_og_title(self):
        html = """
        <html>
          <head>
            <title>fallback</title>
            <meta property="og:title" content="公众号文章标题">
          </head>
        </html>
        """
        self.assertEqual(_html_title(html), "公众号文章标题")

    def test_detect_wechat_unavailable_page(self):
        html = "<html><body>当前环境异常，请完成验证码</body></html>"
        self.assertTrue(
            looks_like_unavailable_wechat_page(html, "https://mp.weixin.qq.com/s/example")
        )

    def test_blogger_by_text_accepts_display_name(self):
        blogger = blogger_by_text([Blogger()], "蓝鲸跃财")
        self.assertEqual(blogger.id, "lanjing")

    def test_manual_submission_article_text_bypasses_url_fetch(self):
        store = FeishuStore.__new__(FeishuStore)
        rec = {
            "record_id": "sub1",
            "fields": {
                "blogger": "蓝鲸跃财",
                "article_url": {"link": "https://mp.weixin.qq.com/s/manual", "text": "手动文章"},
                "title": "手动文章",
                "article_text": "今天加仓测试基金一万元，理由是测试。" * 5,
                "status": "待处理",
            },
        }

        item = _article_from_submission(Settings(), store, rec)

        self.assertEqual(item.blogger_id, "lanjing")
        self.assertEqual(item.title, "手动文章")
        self.assertEqual(item.url, "https://mp.weixin.qq.com/s/manual")
        self.assertGreater(len(item.content_text), 80)

    def test_find_existing_operation_matches_article_and_operation_key(self):
        store = FeishuStore.__new__(FeishuStore)
        target_article = article(url="https://mp.weixin.qq.com/s/MjomoaVpFLxplYRBGhhn1Q")
        target_op = ParsedOperation(
            action="买入",
            fund_code="012345",
            fund_name="测试基金",
            fund_name_raw="测试基金",
            fund_code_source="text",
            sector="半导体",
            amount_or_ratio="1万",
            reason="测试",
            confidence=0.9,
            source="text",
        )
        store.list_records = lambda table: [
            {
                "record_id": "op-existing",
                "fields": {
                    "article_guid": target_article.guid,
                    "article_url": {"link": target_article.url, "text": target_article.title},
                    "action": "买入",
                    "fund_code": "012345",
                    "fund_name": "测试基金",
                    "sector": "半导体",
                    "amount_or_ratio": "1万",
                },
            }
        ]

        found = store.find_existing_operation(target_article, target_op)

        self.assertEqual(found["record_id"], "op-existing")

    def test_save_operation_reuses_existing_operation_record(self):
        store = FeishuStore.__new__(FeishuStore)
        target_article = article(url="https://mp.weixin.qq.com/s/MjomoaVpFLxplYRBGhhn1Q")
        target_op = ParsedOperation(
            action="买入",
            fund_code="012345",
            fund_name="测试基金",
            fund_name_raw="测试基金",
            fund_code_source="text",
            sector="半导体",
            amount_or_ratio="1万",
            reason="测试",
            confidence=0.9,
            source="text",
        )
        created = []
        store.list_records = lambda table: [
            {
                "record_id": "op-existing",
                "fields": {
                    "article_guid": target_article.guid,
                    "article_url": {"link": target_article.url, "text": target_article.title},
                    "action": "买入",
                    "fund_code": "012345",
                    "fund_name": "测试基金",
                    "sector": "半导体",
                    "amount_or_ratio": "1万",
                },
            }
        ]
        store.create_record = lambda table, fields: created.append((table, fields)) or "op-new"

        record_id = store.save_operation(target_article, target_op)

        self.assertEqual(record_id, "op-existing")
        self.assertEqual(created, [])

    def test_active_bloggers_use_bloggers_status(self):
        store = FeishuStore.__new__(FeishuStore)
        store._token = ""
        store._token_expires = 0.0
        store._blogger_record_by_text = {}
        store._blogger_text_by_record = {}
        store._blogger_status_by_text = {}
        store._blogger_maps_loaded = False
        store.list_records = lambda table: [
            {"record_id": "rec1", "fields": {"blogger_id": "lanjing", "status": "启用"}},
            {"record_id": "rec2", "fields": {"blogger_id": "tiantian", "status": "停用"}},
            {"record_id": "rec3", "fields": {"blogger_id": "yage", "status": ""}},
        ]

        self.assertEqual(store.get_active_blogger_ids(), {"lanjing", "yage"})

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

    def test_poll_rss_failure_updates_health_and_continues(self):
        store = FakeStore()
        pipeline = FakePipeline()
        with patch("src.jobs.poll.poll_rss", side_effect=RuntimeError("rss down")):
            processed = process_blogger(
                Blogger(),
                pipeline,
                store,
                FakeSeen(),
                FakeNotifier(),
                dry_run=False,
                limit=5,
            )
        self.assertEqual(processed, 0)
        self.assertEqual(pipeline.calls, 0)
        self.assertEqual(store.health_updates[0][1]["success"], False)
        self.assertEqual(store.health_updates[0][1]["error"], "rss down")

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

    def test_force_reparse_existing_final_article(self):
        today_article = article()
        store = FakeStore()
        store.articles_by_url[today_article.url] = {
            "record_id": "art1",
            "fields": {"status": "无操作", "article_url": {"link": today_article.url}},
        }
        pipeline = FakePipeline()
        with patch("src.jobs.poll.poll_rss", return_value=[today_article]):
            processed = process_blogger(
                Blogger(),
                pipeline,
                store,
                FakeSeen(),
                FakeNotifier(),
                False,
                limit=5,
                force_all=True,
            )
        self.assertEqual(processed, 1)
        self.assertEqual(pipeline.calls, 1)
        self.assertEqual(len(store.saved_ops), 1)

    def test_source_status_classifies_missing_bloggers(self):
        store = FeishuStore.__new__(FeishuStore)
        since = datetime(2026, 7, 3, tzinfo=timezone.utc)
        store.list_records = lambda table: [
            {
                "record_id": "rec1",
                "fields": {
                    "blogger_id": "lanjing",
                    "last_checked_at": int(since.timestamp() * 1000),
                    "last_error": "503 Service Unavailable",
                },
            },
            {
                "record_id": "rec2",
                "fields": {
                    "blogger_id": "tiantian",
                    "last_checked_at": int(since.timestamp() * 1000),
                    "last_error": "",
                },
            },
            {
                "record_id": "rec3",
                "fields": {
                    "blogger_id": "yage",
                    "last_checked_at": int((since - timedelta(days=1)).timestamp() * 1000),
                    "last_error": "",
                },
            },
        ]

        failed, unchecked, not_found = _source_status(
            store,
            {"lanjing", "tiantian", "yage"},
            set(),
            since,
        )

        self.assertEqual(failed, ["lanjing"])
        self.assertEqual(unchecked, ["yage"])
        self.assertEqual(not_found, ["tiantian"])


if __name__ == "__main__":
    unittest.main()
