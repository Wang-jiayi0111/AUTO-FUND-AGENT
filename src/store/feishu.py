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
            url = self._field_text(rec, "article_url")
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
    ) -> str:
        op_id = str(uuid.uuid4())
        fields = {
            "op_id": op_id,
            "blogger_id": self._blogger_link(article.blogger_id),
            "action": op.action,
            "fund_code": op.fund_code,
            "fund_name": op.fund_name or op.fund_name_raw,
            "sector": op.sector,
            "amount_or_ratio": op.amount_or_ratio,
            "reason": op.reason,
            "confidence": op.confidence,
            "article_url": {"link": article.url, "text": article.title},
            "status": status,
        }
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
    ) -> str:
        op_id = str(uuid.uuid4())
        fields = {
            "op_id": op_id,
            "blogger_id": self._blogger_link(article.blogger_id),
            "action": op.action,
            "fund_code": "",
            "fund_name": op.sector or op.fund_name,
            "sector": op.sector,
            "amount_or_ratio": op.amount_or_ratio,
            "reason": op.reason,
            "confidence": op.confidence,
            "article_url": {"link": article.url, "text": article.title},
            "status": "风险提示",
        }
        published_ms = self._dt_ms(article.published_at)
        if published_ms:
            fields["published_at"] = published_ms
        return self.create_record("operations", fields)

    def save_pending_review(
        self,
        article: ArticleItem,
        op: ParsedOperation,
        raw_json: dict[str, Any],
    ) -> str:
        review_id = str(uuid.uuid4())
        candidates = [
            {"code": c.code, "name": c.name, "fund_type": c.fund_type}
            for c in op.code_candidates
        ]
        fields = {
            "review_id": review_id,
            "raw_json": json.dumps(raw_json, ensure_ascii=False),
            "fund_name": op.fund_name or op.fund_name_raw,
            "code_candidates": json.dumps(candidates, ensure_ascii=False),
            "article_url": {"link": article.url, "text": article.title},
            "confidence": op.confidence,
            "status": "待确认",
        }
        return self.create_record("pending_review", fields)

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
            published = rec.get("fields", {}).get("published_at")
            if isinstance(published, (int, float)) and published >= since_ms:
                result.append(rec)
        return result

    def get_pending_reviews(self) -> list[dict[str, Any]]:
        pending = []
        for rec in self.list_records("pending_review"):
            status = self._field_text(rec, "status")
            if status == "待确认":
                pending.append(rec)
        return pending

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
