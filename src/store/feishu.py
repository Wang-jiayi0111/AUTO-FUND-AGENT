from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import Settings
from src.models import ArticleItem, ParsedOperation
from src.utils.fund_name import normalize_fund_name

FEISHU_API = "https://open.feishu.cn/open-apis"

ARTICLE_STATUS_PENDING = "待解析"
ARTICLE_STATUS_PARSING = "解析中"
ARTICLE_STATUS_PARSED = "已解析"
ARTICLE_STATUS_NO_OPS = "无操作"
ARTICLE_STATUS_REVIEW = "待确认"
ARTICLE_STATUS_FAILED = "解析失败"
ARTICLE_STATUS_IGNORED = "已忽略"

FINAL_ARTICLE_STATUSES = {
    ARTICLE_STATUS_PARSED,
    ARTICLE_STATUS_NO_OPS,
    ARTICLE_STATUS_REVIEW,
    ARTICLE_STATUS_IGNORED,
}


class FeishuStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token = ""
        self._token_expires = 0.0
        self._blogger_record_by_text: dict[str, str] = {}
        self._blogger_text_by_record: dict[str, str] = {}
        self._blogger_maps_loaded = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        url = f"{FEISHU_API}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.settings.feishu_app_id,
            "app_secret": self.settings.feishu_app_secret,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        return self._token

    def _table_id(self, name: str) -> str:
        table_id = self.settings.feishu_tables.get(name, "")
        if not table_id:
            raise ValueError(f"Missing Feishu table id for {name}")
        return table_id

    def list_records(
        self,
        table: str,
        page_size: int = 100,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        table_id = self._table_id(table)
        url = f"{FEISHU_API}/bitable/v1/apps/{self.settings.feishu_app_token}/tables/{table_id}/records"
        items: list[dict[str, Any]] = []
        page_token = None
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            if filter_expr:
                params["filter"] = filter_expr
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(url, headers=self._headers(), params=params)
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu list failed: {data}")
            items.extend(data["data"].get("items", []))
            page_token = data["data"].get("page_token")
            if not page_token:
                break
        return items

    def create_record(self, table: str, fields: dict[str, Any]) -> str:
        table_id = self._table_id(table)
        url = f"{FEISHU_API}/bitable/v1/apps/{self.settings.feishu_app_token}/tables/{table_id}/records"
        payload = {"fields": fields}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu create failed: {data}")
        return data["data"]["record"]["record_id"]

    def update_record(self, table: str, record_id: str, fields: dict[str, Any]) -> None:
        table_id = self._table_id(table)
        url = (
            f"{FEISHU_API}/bitable/v1/apps/{self.settings.feishu_app_token}"
            f"/tables/{table_id}/records/{record_id}"
        )
        with httpx.Client(timeout=30.0) as client:
            resp = client.put(url, headers=self._headers(), json={"fields": fields})
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu update failed: {data}")

    @staticmethod
    def _field_text(record: dict[str, Any], key: str) -> str:
        val = record.get("fields", {}).get(key)
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict):
                return str(first.get("text", ""))
            return str(first)
        if isinstance(val, dict):
            return str(val.get("text", val.get("value", "")))
        return str(val or "")

    @staticmethod
    def _field_url(record: dict[str, Any], key: str) -> str:
        val = record.get("fields", {}).get(key)
        if isinstance(val, dict):
            return str(val.get("link") or val.get("url") or val.get("text") or "")
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict):
                return str(first.get("link") or first.get("url") or first.get("text") or "")
            return str(first)
        return str(val or "")

    @staticmethod
    def _field_number(record: dict[str, Any], key: str) -> int | float | None:
        val = record.get("fields", {}).get(key)
        if isinstance(val, (int, float)):
            return val
        return None

    @staticmethod
    def _link_record_ids(record: dict[str, Any], key: str) -> list[str]:
        val = record.get("fields", {}).get(key)
        if not isinstance(val, list):
            return []
        ids: list[str] = []
        for item in val:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                record_id = item.get("record_id") or item.get("id") or item.get("text")
                if record_id:
                    ids.append(str(record_id))
        return ids

    def _load_blogger_maps(self) -> None:
        if self._blogger_maps_loaded:
            return
        for rec in self.list_records("bloggers"):
            text_id = self._field_text(rec, "blogger_id")
            if text_id:
                self._blogger_record_by_text[text_id] = rec["record_id"]
                self._blogger_text_by_record[rec["record_id"]] = text_id
        self._blogger_maps_loaded = True

    def _blogger_link(self, blogger_id: str) -> list[str]:
        self._load_blogger_maps()
        record_id = self._blogger_record_by_text.get(blogger_id)
        if not record_id:
            raise ValueError(
                f"Bloggers table has no row with blogger_id={blogger_id!r}. "
                "Add the blogger in Feishu Bloggers first."
            )
        return [record_id]

    def blogger_id_from_field(self, record: dict[str, Any], key: str = "blogger_id") -> str:
        """Resolve a link field to the Bloggers.blogger_id text (e.g. lanjing)."""
        text = self._field_text(record, key)
        if not text:
            return ""
        self._load_blogger_maps()
        return self._blogger_text_by_record.get(text, text)

    def get_seen_article_guids(self) -> set[str]:
        records = self.list_records("operations")
        guids: set[str] = set()
        for rec in records:
            url = self._field_url(rec, "article_url")
            if url:
                guids.add(url)
        return guids

    def _dt_ms(self, dt: datetime | None) -> int | None:
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    def save_operation(
        self,
        article: ArticleItem,
        op: ParsedOperation,
        status: str = "自动入库",
        article_record_id: str | None = None,
        source: str | None = None,
    ) -> str:
        op_id = str(uuid.uuid4())
        fields = {
            "op_id": op_id,
            "blogger_id": self._blogger_link(article.blogger_id),
            "article_guid": article.guid,
            "action": op.action,
            "fund_code": op.fund_code,
            "fund_name": op.fund_name or op.fund_name_raw,
            "sector": op.sector,
            "amount_or_ratio": op.amount_or_ratio,
            "reason": op.reason,
            "confidence": op.confidence,
            "source": source or op.source,
            "article_url": {"link": article.url, "text": article.title},
            "status": status,
            "created_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
        }
        if article_record_id:
            fields["article_id"] = [article_record_id]
        published_ms = self._dt_ms(article.published_at)
        if published_ms:
            fields["published_at"] = published_ms
        record_id = self.create_record("operations", fields)
        self._upsert_fund_mapping(article, op, record_id)
        return record_id

    def save_sector_alert(
        self,
        article: ArticleItem,
        op: ParsedOperation,
        article_record_id: str | None = None,
    ) -> str:
        op_id = str(uuid.uuid4())
        fields = {
            "op_id": op_id,
            "blogger_id": self._blogger_link(article.blogger_id),
            "article_guid": article.guid,
            "action": op.action,
            "fund_code": "",
            "fund_name": op.sector or op.fund_name,
            "sector": op.sector,
            "amount_or_ratio": op.amount_or_ratio,
            "reason": op.reason,
            "confidence": op.confidence,
            "source": op.source,
            "article_url": {"link": article.url, "text": article.title},
            "status": "风险提示",
            "created_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
        }
        if article_record_id:
            fields["article_id"] = [article_record_id]
        published_ms = self._dt_ms(article.published_at)
        if published_ms:
            fields["published_at"] = published_ms
        return self.create_record("operations", fields)

    def save_pending_review(
        self,
        article: ArticleItem,
        op: ParsedOperation,
        raw_json: dict[str, Any],
        article_record_id: str | None = None,
    ) -> str:
        review_id = str(uuid.uuid4())
        candidates = [
            {"code": c.code, "name": c.name, "fund_type": c.fund_type}
            for c in op.code_candidates
        ]
        fields = {
            "review_id": review_id,
            "raw_json": json.dumps(raw_json, ensure_ascii=False),
            "blogger_id": self._blogger_link(article.blogger_id),
            "action": op.action,
            "fund_code": op.fund_code,
            "fund_name": op.fund_name or op.fund_name_raw,
            "sector": op.sector,
            "amount_or_ratio": op.amount_or_ratio,
            "reason": op.reason,
            "source": op.source,
            "code_candidates": json.dumps(candidates, ensure_ascii=False),
            "article_url": {"link": article.url, "text": article.title},
            "confidence": op.confidence,
            "status": "待确认",
        }
        if article_record_id:
            fields["article_id"] = [article_record_id]
        published_ms = self._dt_ms(article.published_at)
        if published_ms:
            fields["published_at"] = published_ms
        return self.create_record("pending_review", fields)

    def find_article(self, guid: str, url: str) -> dict[str, Any] | None:
        for rec in self.list_records("articles"):
            rec_guid = self._field_text(rec, "guid")
            rec_url = self._field_url(rec, "article_url")
            if guid and rec_guid and guid == rec_guid:
                return rec
            if url and rec_url and url == rec_url:
                return rec
        return None

    def create_article(
        self,
        article: ArticleItem,
        discovered_at: datetime | None = None,
        status: str = ARTICLE_STATUS_PENDING,
    ) -> str:
        now = discovered_at or datetime.now(tz=timezone.utc)
        article_id = str(uuid.uuid4())
        fields: dict[str, Any] = {
            "article_id": article_id,
            "blogger_id": self._blogger_link(article.blogger_id),
            "guid": article.guid,
            "title": article.title,
            "article_url": {"link": article.url, "text": article.title},
            "discovered_at": self._dt_ms(now),
            "status": status,
            "operation_count": 0,
            "pending_review_count": 0,
            "raw_excerpt": article.content_text[:2000],
        }
        published_ms = self._dt_ms(article.published_at)
        if published_ms:
            fields["published_at"] = published_ms
        return self.create_record("articles", fields)

    def update_article(self, record_id: str, fields: dict[str, Any]) -> None:
        self.update_record("articles", record_id, fields)

    def mark_article_parsing(self, record_id: str) -> None:
        self.update_article(record_id, {"status": ARTICLE_STATUS_PARSING, "last_error": ""})

    def mark_article_done(
        self,
        record_id: str,
        status: str,
        operation_count: int,
        pending_review_count: int,
        raw_json: dict[str, Any] | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "status": status,
            "operation_count": operation_count,
            "pending_review_count": pending_review_count,
            "parsed_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
            "last_error": "",
        }
        if raw_json is not None:
            fields["raw_json"] = json.dumps(raw_json, ensure_ascii=False)
        self.update_article(record_id, fields)

    def mark_article_failed(self, record_id: str, error: str) -> None:
        self.update_article(
            record_id,
            {
                "status": ARTICLE_STATUS_FAILED,
                "last_error": error[:2000],
                "parsed_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
            },
        )

    def article_record_id_from_field(self, record: dict[str, Any], key: str = "article_id") -> str:
        ids = self._link_record_ids(record, key)
        return ids[0] if ids else ""

    def get_articles_since(self, since: datetime) -> list[dict[str, Any]]:
        since_ms = int(since.timestamp() * 1000)
        result: list[dict[str, Any]] = []
        for rec in self.list_records("articles"):
            discovered = self._field_number(rec, "discovered_at")
            published = self._field_number(rec, "published_at")
            marker = discovered if discovered is not None else published
            if isinstance(marker, (int, float)) and marker >= since_ms:
                result.append(rec)
        return result

    def get_failed_articles_since(self, since: datetime) -> list[dict[str, Any]]:
        return [
            rec for rec in self.get_articles_since(since)
            if self._field_text(rec, "status") == ARTICLE_STATUS_FAILED
        ]

    def update_blogger_health(
        self,
        blogger_id: str,
        *,
        checked_at: datetime | None = None,
        success: bool,
        article: ArticleItem | None = None,
        error: str = "",
    ) -> None:
        self._load_blogger_maps()
        record_id = self._blogger_record_by_text.get(blogger_id)
        if not record_id:
            return
        now_ms = self._dt_ms(checked_at or datetime.now(tz=timezone.utc))
        fields: dict[str, Any] = {"last_checked_at": now_ms}
        if success:
            fields["last_success_at"] = now_ms
            fields["last_error"] = ""
            fields["consecutive_failures"] = 0
            if article:
                fields["last_article_title"] = article.title
                fields["last_article_url"] = {"link": article.url, "text": article.title}
                published_ms = self._dt_ms(article.published_at)
                if published_ms:
                    fields["last_published_at"] = published_ms
        else:
            fields["last_error"] = error[:2000]
        self.update_record("bloggers", record_id, fields)

    def _upsert_fund_mapping(
        self,
        article: ArticleItem,
        op: ParsedOperation,
        operation_record_id: str,
    ) -> None:
        records = self.list_records("fund_mapping")
        norm_name = normalize_fund_name(op.fund_name or op.fund_name_raw)
        match_id = None
        for rec in records:
            blogger = self.blogger_id_from_field(rec, "blogger_id")
            code = self._field_text(rec, "fund_code")
            name = normalize_fund_name(self._field_text(rec, "fund_name"))
            if blogger != article.blogger_id:
                continue
            if op.fund_code and code == op.fund_code:
                match_id = rec["record_id"]
                break
            if not op.fund_code and name and name == norm_name:
                match_id = rec["record_id"]
                break

        fields = {
            "blogger_id": self._blogger_link(article.blogger_id),
            "fund_code": op.fund_code,
            "fund_name": norm_name or op.fund_name_raw,
            "fund_name_raw": op.fund_name_raw,
            "sector": op.sector,
            "latest_action": op.action,
            "latest_op_id": [operation_record_id],
            "updated_at": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
        }
        if match_id:
            self.update_record("fund_mapping", match_id, fields)
        else:
            fields["mapping_id"] = str(uuid.uuid4())
            self.create_record("fund_mapping", fields)

    def get_active_follow_bloggers(self) -> set[str]:
        ids: set[str] = set()
        for rec in self.list_records("follow_list"):
            active = rec.get("fields", {}).get("active")
            if active is False:
                continue
            blogger = self.blogger_id_from_field(rec, "blogger_id")
            if blogger:
                ids.add(blogger)
        return ids

    def get_active_focus_items(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for rec in self.list_records("focus_list"):
            active = rec.get("fields", {}).get("active")
            if active is False:
                continue
            items.append(
                {
                    "blogger_id": self.blogger_id_from_field(rec, "blogger_id"),
                    "fund_code": self._field_text(rec, "fund_code"),
                    "fund_name": normalize_fund_name(self._field_text(rec, "fund_name")),
                }
            )
        return items

    def get_operations_since(self, since: datetime) -> list[dict[str, Any]]:
        since_ms = int(since.timestamp() * 1000)
        result = []
        for rec in self.list_records("operations"):
            created = rec.get("fields", {}).get("created_at")
            published = rec.get("fields", {}).get("published_at")
            marker = created if isinstance(created, (int, float)) else published
            if isinstance(marker, (int, float)) and marker >= since_ms:
                result.append(rec)
        return result

    def get_pending_reviews(self) -> list[dict[str, Any]]:
        pending = []
        for rec in self.list_records("pending_review"):
            status = self._field_text(rec, "status")
            if status == "待确认":
                pending.append(rec)
        return pending

    def get_reviews_to_apply(self) -> list[dict[str, Any]]:
        reviews: list[dict[str, Any]] = []
        for rec in self.list_records("pending_review"):
            status = self._field_text(rec, "status")
            processed_at = self._field_number(rec, "processed_at")
            if status in {"已通过", "已拒绝"} and processed_at is None:
                reviews.append(rec)
        return reviews

    def record_link(self, table_key: str, record_id: str) -> str:
        base = self.settings.feishu_base_url.rstrip("/")
        table_id = self._table_id(table_key)
        if base:
            return f"{base}?table={table_id}&record={record_id}"
        return f"feishu://table/{table_id}/record/{record_id}"

    def get_blogger_name_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for rec in self.list_records("bloggers"):
            blogger_id = self._field_text(rec, "blogger_id")
            name = self._field_text(rec, "name") or blogger_id
            if blogger_id:
                mapping[blogger_id] = name
        return mapping
