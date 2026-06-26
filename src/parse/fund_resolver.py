from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from src.models import FundCandidate
from src.utils.fund_name import (
    candidate_matches_share_class,
    clean_fund_text,
    fund_name_match_score,
    fund_names_equivalent,
    fund_search_queries,
    fund_share_class_hint,
    is_valid_fund_code,
    normalize_fund_name,
)

EASTMONEY_SEARCH_URL = (
    "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
)

_MATCH_SCORE_THRESHOLD = 0.85


@dataclass
class ResolveResult:
    fund_code: str
    fund_name: str
    fund_name_raw: str
    fund_code_source: str
    candidates: list[FundCandidate]
    resolved: bool
    unique_match: bool


class FundResolver:
    def __init__(self, cache_dir: Path, cache_ttl_seconds: int = 7 * 24 * 3600):
        self.cache_dir = cache_dir
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self.cache_dir / "fund_search_cache.json"
        self._cache: dict[str, Any] = self._load_cache()

    def _load_cache(self) -> dict[str, Any]:
        if not self._cache_file.exists():
            return {}
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_cache(self) -> None:
        self._cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_cached(self, key: str) -> list[dict[str, str]] | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > self.cache_ttl_seconds:
            return None
        return entry.get("items")

    def _set_cached(self, key: str, items: list[FundCandidate]) -> None:
        self._cache[key] = {
            "ts": time.time(),
            "items": [{"code": c.code, "name": c.name, "fund_type": c.fund_type} for c in items],
        }
        self._save_cache()

    @staticmethod
    def _is_fund_row(row: dict[str, Any]) -> bool:
        code = str(row.get("CODE", "")).strip()
        if not re.fullmatch(r"\d{6}", code):
            return False
        category = str(row.get("CATEGORYDESC") or "")
        if category == "基金":
            return True
        return isinstance(row.get("FundBaseInfo"), dict) and bool(row.get("FundBaseInfo"))

    def _fetch_search_rows(self, query: str) -> list[dict[str, Any]]:
        url = f"{EASTMONEY_SEARCH_URL}?m=1&key={quote(query)}"
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers={"User-Agent": "AUTO-FUND-AGENT/1.0"})
            resp.raise_for_status()
            payload = resp.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return payload.get("Datas") or payload.get("data") or []
        return []

    @staticmethod
    def _is_fund_candidate(candidate: FundCandidate) -> bool:
        if not is_valid_fund_code(candidate.code):
            return False
        if candidate.fund_type and candidate.fund_type != "基金":
            return False
        return True

    def search(self, query: str) -> list[FundCandidate]:
        cache_key = clean_fund_text(query)
        if not cache_key:
            return []
        cached = self._get_cached(cache_key)
        if cached is not None:
            return [
                FundCandidate(**item)
                for item in cached
                if self._is_fund_candidate(FundCandidate(**item))
            ]

        try:
            rows = self._fetch_search_rows(cache_key)
        except (httpx.HTTPError, json.JSONDecodeError):
            return []

        items: list[FundCandidate] = []
        seen_codes: set[str] = set()
        for row in rows:
            if not self._is_fund_row(row):
                continue
            code = str(row.get("CODE", "")).strip()
            name = str(row.get("NAME", "")).strip()
            if not code or not name or code in seen_codes:
                continue
            seen_codes.add(code)
            fund_type = str(row.get("CATEGORYDESC") or row.get("TYPE") or "")
            base = row.get("FundBaseInfo") or {}
            if not fund_type and isinstance(base, dict):
                fund_type = str(base.get("FTYPE") or "")
            items.append(FundCandidate(code=code, name=name, fund_type=fund_type))

        if items:
            self._set_cached(cache_key, items)
        return items

    def search_with_fallbacks(self, raw_name: str) -> list[FundCandidate]:
        merged: list[FundCandidate] = []
        seen_codes: set[str] = set()
        for query in fund_search_queries(raw_name):
            for candidate in self.search(query):
                if candidate.code in seen_codes:
                    continue
                seen_codes.add(candidate.code)
                merged.append(candidate)
        return merged

    def _pick_unique_match(
        self, raw_name: str, candidates: list[FundCandidate]
    ) -> FundCandidate | None:
        if not candidates:
            return None

        fund_candidates = [c for c in candidates if self._is_fund_candidate(c)]
        if not fund_candidates:
            return None

        exact = [c for c in fund_candidates if c.name == raw_name]
        if len(exact) == 1:
            return exact[0]

        equivalent = [c for c in fund_candidates if fund_names_equivalent(raw_name, c.name)]
        if len(equivalent) == 1:
            return equivalent[0]

        share_class = fund_share_class_hint(raw_name)
        if share_class and equivalent:
            class_matches = [
                c for c in equivalent if candidate_matches_share_class(c.name, share_class)
            ]
            if len(class_matches) == 1:
                return class_matches[0]

        normalized = normalize_fund_name(raw_name)
        same_base = [
            c
            for c in fund_candidates
            if normalize_fund_name(c.name) == normalized or c.name == raw_name
        ]
        if len(same_base) == 1:
            return same_base[0]

        if share_class and same_base:
            class_matches = [
                c for c in same_base if candidate_matches_share_class(c.name, share_class)
            ]
            if len(class_matches) == 1:
                return class_matches[0]

        scored = sorted(
            ((fund_name_match_score(raw_name, c.name), c) for c in fund_candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        top_score, top_match = scored[0]
        if top_score < _MATCH_SCORE_THRESHOLD:
            return None
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if second_score >= _MATCH_SCORE_THRESHOLD and abs(top_score - second_score) < 0.03:
            return None
        return top_match

    def resolve(self, fund_name: str, fund_code: str = "") -> ResolveResult:
        raw_name = fund_name or ""
        code = fund_code.strip()
        if is_valid_fund_code(code):
            return ResolveResult(
                fund_code=code,
                fund_name=normalize_fund_name(raw_name) or raw_name,
                fund_name_raw=raw_name,
                fund_code_source="ocr",
                candidates=[],
                resolved=True,
                unique_match=True,
            )

        candidates = self.search_with_fallbacks(raw_name) if raw_name else []
        match = self._pick_unique_match(raw_name, candidates)
        if match:
            return ResolveResult(
                fund_code=match.code,
                fund_name=match.name,
                fund_name_raw=raw_name,
                fund_code_source="search",
                candidates=candidates,
                resolved=True,
                unique_match=True,
            )

        return ResolveResult(
            fund_code="",
            fund_name=normalize_fund_name(raw_name),
            fund_name_raw=raw_name,
            fund_code_source="unknown",
            candidates=candidates,
            resolved=False,
            unique_match=False,
        )
