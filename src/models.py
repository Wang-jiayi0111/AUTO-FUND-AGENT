from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FundCandidate:
    code: str
    name: str
    fund_type: str = ""


@dataclass
class ParsedOperation:
    action: str
    fund_code: str
    fund_name: str
    fund_name_raw: str
    fund_code_source: str
    sector: str
    amount_or_ratio: str
    reason: str
    confidence: float
    source: str
    code_candidates: list[FundCandidate] = field(default_factory=list)


@dataclass
class ArticleItem:
    blogger_id: str
    blogger_name: str
    title: str
    url: str
    guid: str
    published_at: datetime | None
    content_html: str
    content_text: str
    image_urls: list[str]


@dataclass
class ParseResult:
    article: ArticleItem
    operations: list[ParsedOperation]
    raw_json: dict[str, Any]
