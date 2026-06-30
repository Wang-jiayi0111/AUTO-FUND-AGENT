from __future__ import annotations

import re
from typing import Any

from src.config import Settings
from src.ingest.rss_poller import enrich_article_images
from src.models import ArticleItem, ParsedOperation, ParseResult
from src.parse.fund_resolver import FundResolver
from src.parse.llm_extractor import LLMExtractor
from src.utils.fund_name import is_valid_fund_code, normalize_fund_name


ACTIONS = {"买入", "卖出", "加仓", "减仓", "定投", "观望"}

_ACTION_ALIASES = {
    "买入确认中": "买入",
    "卖出确认中": "卖出",
    "种植": "定投",
}

_ACTION_PRIORITY = {"定投": 4, "加仓": 3, "减仓": 3, "买入": 2, "卖出": 2, "观望": 0}

_FUND_NAME_MARKERS = ("基金", "ETF", "混合", "联接", "LOF", "指数", "债券", "理财")
_FUND_COMPANY_HINTS = (
    "景顺", "天弘", "华夏", "易方达", "广发", "富国", "招商", "诺安", "鹏华", "中欧",
    "工银", "嘉实", "博时", "华安", "银华", "永赢", "华泰", "南方", "汇添富", "兴全",
    "中庚", "万家", "大成", "国投", "平安", "中银", "建信", "交银", "农银", "国联",
    "东财", "恒生", "国寿", "中金", "贝莱德", "长城", "中信", "申万", "摩根", "海富通",
)
_SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "半导体": ("半导体", "芯片"),
    "存储芯片": ("存储", "芯片"),
    "CPO": ("CPO", "光模块", "互联", "算力"),
    "航天": ("航天", "卫星"),
    "海外": ("海外", "QDII", "恒生", "标普", "纳斯达克"),
    "中小盘": ("中小盘", "多策略", "灵活配置"),
    "国产算力": ("算力", "半导体", "芯片"),
    "创新药": ("创新药", "医药", "港股通"),
    "汽车": ("汽车", "新能源车", "电动汽车"),
    "红利": ("红利", "股息"),
}
_VAGUE_AMOUNT_PHRASES = (
    "一点", "重仓", "调仓", "少量", "一些", "布局", "继续", "微调", "不动",
)
_SECTOR_THEME_NAMES = frozenset({
    "半导体", "黄金", "白银", "煤炭", "军工", "新能源", "光伏", "储能", "医药", "白酒",
    "消费", "红利", "微盘", "债基", "人工智能", "芯片", "光模块", "机器人", "卫星",
    "国产算力", "有色", "算力",
})


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "null" else text


def _normalize_action(action: str) -> str:
    action = action.strip()
    if action in _ACTION_ALIASES:
        return _ACTION_ALIASES[action]
    if action in ACTIONS:
        return action
    if "买入" in action:
        return "买入"
    if "卖出" in action:
        return "卖出"
    if "加仓" in action:
        return "加仓"
    if "减仓" in action:
        return "减仓"
    if "定投" in action:
        return "定投"
    return "观望"


def _format_amount_value(key: str, value: Any) -> str:
    if isinstance(value, (int, float)):
        if key == "shares":
            return f"{value:,.2f}份"
        return f"{value:,.2f}元"
    return _coerce_str(value)


def _extract_amount(op: dict[str, Any]) -> str:
    for key in ("amount_or_ratio", "amount", "shares"):
        value = op.get(key)
        if value is None or value == "":
            continue
        if key == "amount_or_ratio":
            text = _coerce_str(value)
            if text:
                return text
        else:
            return _format_amount_value(key, value)
    return ""


def _infer_action(op: dict[str, Any]) -> str:
    action = _coerce_str(op.get("action"))
    if action:
        return _normalize_action(action)
    trade_type = _coerce_str(op.get("type"))
    if trade_type:
        return _normalize_action(trade_type)
    if op.get("shares") not in (None, ""):
        return "卖出"
    if op.get("amount") not in (None, ""):
        return "买入"
    return "观望"


def _amount_to_yuan(text: str) -> float | None:
    if not text:
        return None
    cleaned = text.replace(",", "").replace("，", "")
    match = re.search(r"([\d.]+)\s*万", cleaned)
    if match:
        return float(match.group(1)) * 10000
    match = re.search(r"([\d.]+)", cleaned)
    if not match:
        return None
    value = float(match.group(1))
    if "份" in cleaned and value > 0:
        return None
    return value


def _amounts_match(left: str, right: str, tolerance: float = 0.05) -> bool:
    left_yuan = _amount_to_yuan(left)
    right_yuan = _amount_to_yuan(right)
    if left_yuan is None or right_yuan is None:
        return False
    if left_yuan <= 0 or right_yuan <= 0:
        return False
    return abs(left_yuan - right_yuan) / max(left_yuan, right_yuan) <= tolerance


def _action_side(action: str) -> str:
    if action in {"买入", "加仓", "定投"}:
        return "buy"
    if action in {"卖出", "减仓"}:
        return "sell"
    return "other"


def _names_match(short: str, full: str) -> bool:
    if not short or not full:
        return False
    short_norm = normalize_fund_name(short)
    full_norm = normalize_fund_name(full)
    if not short_norm or not full_norm:
        return False
    if short_norm in full_norm or full_norm in short_norm:
        return True
    if len(short_norm) >= 2 and short_norm[:2] in full_norm:
        return True
    return False


def _prefer_action(left: str, right: str) -> str:
    left_priority = _ACTION_PRIORITY.get(left, 1)
    right_priority = _ACTION_PRIORITY.get(right, 1)
    return left if left_priority >= right_priority else right


def _looks_like_sector_alias(fund_name: str, sector: str = "") -> bool:
    """Theme/sector nicknames bloggers use instead of fund product names."""
    name = _coerce_str(fund_name)
    if not name:
        return False
    if any(marker in name for marker in _FUND_NAME_MARKERS):
        return False
    if any(hint in name for hint in _FUND_COMPANY_HINTS):
        return False
    if re.fullmatch(r"[A-Z0-9]{2,8}", name):
        return True
    if name in _SECTOR_THEME_NAMES:
        return True
    sector_norm = _coerce_str(sector)
    if sector_norm and (name == sector_norm or name in sector_norm or sector_norm in name):
        return True
    if "金" in name and sector_norm in {"黄金", "贵金属"}:
        return True
    if len(name) <= 4 and name.endswith("金") and sector_norm in {"黄金", "贵金属", ""}:
        return True
    return False


def _is_real_fund_op(op: dict[str, Any]) -> bool:
    if _coerce_str(op.get("fund_code")):
        return True
    name = _coerce_str(op.get("fund_name"))
    if not name:
        return False
    if any(marker in name for marker in _FUND_NAME_MARKERS):
        return True
    if any(hint in name for hint in _FUND_COMPANY_HINTS):
        return True
    return len(normalize_fund_name(name)) > 6


def _is_covered_by_real_fund_op(alias_op: dict[str, Any], ops: list[dict[str, Any]]) -> bool:
    alias_amount = _extract_amount(alias_op)
    alias_side = _action_side(alias_op.get("action", ""))
    for other in ops:
        if other is alias_op or not _is_real_fund_op(other):
            continue
        if _action_side(other.get("action", "")) != alias_side:
            continue
        other_amount = _extract_amount(other)
        if alias_amount and other_amount and _amounts_match(alias_amount, other_amount):
            return True
    return False


def _is_qualitative_amount(text: str) -> bool:
    if not text:
        return True
    cleaned = text.strip().lower().replace(" ", "")
    if re.search(r"\d+\s*w\s*和", cleaned, re.I):
        return True
    if re.search(r"[\d.]+\s*w\b", cleaned, re.I):
        return True
    for phrase in _VAGUE_AMOUNT_PHRASES:
        if phrase in text:
            return True
    if re.fullmatch(r"[\d.]+k", cleaned, re.I):
        return True
    if _amount_to_yuan(text) is not None:
        return False
    return True


def _score_text_for_fund(text_op: dict[str, Any], fund_op: dict[str, Any]) -> int:
    sector = _coerce_str(text_op.get("sector"))
    fund_name = _coerce_str(fund_op.get("fund_name"))
    if not sector or not fund_name:
        return 0
    score = 0
    if sector in fund_name:
        score += 5
    for keyword in _SECTOR_KEYWORDS.get(sector, ()):
        if keyword in fund_name:
            score += 3
    return score


def _score_annotation_for_fund(annotation: dict[str, Any], fund_name: str) -> int:
    sector = _coerce_str(annotation.get("sector"))
    if not sector or not fund_name:
        return 0
    score = 0
    keywords = [sector, *annotation.get("keywords", [])]
    for keyword in keywords:
        kw = _coerce_str(keyword)
        if kw and kw in fund_name:
            score += 3
    for keyword in _SECTOR_KEYWORDS.get(sector, ()):
        if keyword in fund_name:
            score += 2
    return score


def _infer_sector_from_fund_name(fund_name: str) -> str:
    if not fund_name:
        return ""
    for sector, keywords in _SECTOR_KEYWORDS.items():
        if sector in fund_name:
            return sector
        for keyword in keywords:
            if len(keyword) >= 2 and keyword in fund_name:
                return sector
    return ""


def _apply_best_annotation(
    op: dict[str, Any],
    candidates: list[tuple[int, dict[str, Any]]],
    min_score: int = 2,
) -> None:
    if not candidates:
        return
    candidates.sort(key=lambda item: item[0], reverse=True)
    top_score, best = candidates[0]
    if top_score < min_score:
        return
    if len(candidates) > 1 and candidates[1][0] >= min_score:
        if top_score - candidates[1][0] < 2:
            return
    if not _coerce_str(op.get("sector")) and best.get("sector"):
        op["sector"] = best["sector"]
    if not _coerce_str(op.get("reason")) and best.get("reason"):
        op["reason"] = best["reason"]


def _enrich_fund_ops_from_annotations(
    merged: list[dict[str, Any]], annotations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach sector/reason from dedicated body-text analysis pass."""
    for op in merged:
        if not _is_real_fund_op(op):
            continue
        fund_name = _coerce_str(op.get("fund_name"))
        scored = [
            (_score_annotation_for_fund(ann, fund_name), ann)
            for ann in annotations
        ]
        _apply_best_annotation(op, scored)
        if not _coerce_str(op.get("sector")):
            inferred = _infer_sector_from_fund_name(fund_name)
            if inferred:
                op["sector"] = inferred
    return merged


def _filter_analytical_text_operations(
    text_ops: list[dict[str, Any]], image_ops: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """When screenshots contain real trades, drop vague sector-only narrative rows."""
    images = [_normalize_raw_op(op, default_source="image") for op in image_ops]
    if not any(_is_real_fund_op(op) for op in images):
        return text_ops

    kept: list[dict[str, Any]] = []
    for op in text_ops:
        normalized = _normalize_raw_op(op, default_source="text")
        if normalized.get("_sector_alert"):
            kept.append(op)
            continue
        if _is_sector_only_text_op(normalized):
            if _is_qualitative_amount(_extract_amount(normalized)):
                continue
            kept.append(op)
            continue
        if _is_real_fund_op(normalized):
            kept.append(op)
            continue
        sector = _coerce_str(normalized.get("sector"))
        fund_name = _coerce_str(normalized.get("fund_name"))
        if sector and not fund_name:
            continue
        kept.append(op)
    return kept


def _enrich_fund_ops_from_text_analysis(
    merged: list[dict[str, Any]], text_ops: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach sector/reason from analytical text to screenshot fund rows."""
    texts = [_normalize_raw_op(op, default_source="text") for op in text_ops]
    analysis_texts = [op for op in texts if not op.get("_sector_alert")]

    for op in merged:
        if not _is_real_fund_op(op):
            continue
        best_text: dict[str, Any] | None = None
        best_score = 0
        for text_op in analysis_texts:
            text_name = _coerce_str(text_op.get("fund_name"))
            if text_name and not _names_match(text_name, _coerce_str(op.get("fund_name"))):
                continue
            score = _score_text_for_fund(text_op, op)
            if score < 2 and _coerce_str(text_op.get("reason")):
                sector = _coerce_str(text_op.get("sector"))
                if sector:
                    score = _score_annotation_for_fund(
                        {"sector": sector, "keywords": [sector], "reason": text_op.get("reason")},
                        _coerce_str(op.get("fund_name")),
                    )
            if score < 2:
                continue
            if best_text is None or score > best_score:
                best_score = score
                best_text = text_op
            elif score == best_score and best_text is not None:
                new_reason = _coerce_str(text_op.get("reason"))
                old_reason = _coerce_str(best_text.get("reason"))
                if len(new_reason) > len(old_reason):
                    best_text = text_op
        if best_text and best_score >= 2:
            if not _coerce_str(op.get("sector")) and best_text.get("sector"):
                op["sector"] = best_text["sector"]
            if not _coerce_str(op.get("reason")) and best_text.get("reason"):
                op["reason"] = best_text["reason"]
        if not _coerce_str(op.get("sector")):
            inferred = _infer_sector_from_fund_name(_coerce_str(op.get("fund_name")))
            if inferred:
                op["sector"] = inferred
    return merged


def _append_risk_alerts_to_merged(
    merged: list[dict[str, Any]],
    risk_alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn body-text risk alerts into 观望 sector rows for storage/notify."""
    existing_sectors = {
        _coerce_str(op.get("sector"))
        for op in merged
        if _coerce_str(op.get("sector"))
        and (
            op.get("_sector_alert")
            or op.get("action") == "观望"
        )
    }
    for alert in risk_alerts:
        sector = _coerce_str(alert.get("sector"))
        reason = _coerce_str(alert.get("reason"))
        amount = _coerce_str(alert.get("amount_or_ratio"))
        if not sector or sector in existing_sectors:
            continue
        if not reason and not amount:
            continue
        merged.append({
            "action": "观望",
            "fund_code": "",
            "fund_name": "",
            "sector": sector,
            "amount_or_ratio": amount,
            "reason": reason,
            "confidence": float(alert.get("confidence", 0.85)),
            "source": "text",
            "_sector_alert": True,
        })
        existing_sectors.add(sector)
    return merged


def _sanitize_merged_ops(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for op in ops:
        clean = dict(op)
        for key in ("_sector_alert", "_sector_only", "_planting_hint"):
            clean.pop(key, None)
        result.append(clean)
    return result


def _drop_sector_alias_duplicates(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove sector nicknames when the same trade is already represented by a real fund op."""
    result: list[dict[str, Any]] = []
    for op in ops:
        name = _coerce_str(op.get("fund_name"))
        sector = _coerce_str(op.get("sector"))
        if _looks_like_sector_alias(name, sector) and _is_covered_by_real_fund_op(op, ops):
            continue
        result.append(op)
    return result


def _drop_unresolved_sector_aliases(ops: list[ParsedOperation]) -> list[ParsedOperation]:
    """Sector/theme nicknames without a fund code should not enter Operations or PendingReview."""
    result: list[ParsedOperation] = []
    for op in ops:
        if op.action == "观望" and op.sector:
            result.append(op)
            continue
        raw_name = op.fund_name_raw or op.fund_name
        if not op.fund_code and _looks_like_sector_alias(raw_name, op.sector):
            if _is_covered_by_real_fund_parsed(op, ops):
                continue
            continue
        result.append(op)
    return result


def _is_covered_by_real_fund_parsed(
    alias_op: ParsedOperation, ops: list[ParsedOperation]
) -> bool:
    alias_amount = alias_op.amount_or_ratio
    alias_side = _action_side(alias_op.action)
    for other in ops:
        if other is alias_op:
            continue
        if not other.fund_code:
            continue
        if _action_side(other.action) != alias_side:
            continue
        if alias_amount and other.amount_or_ratio and _amounts_match(alias_amount, other.amount_or_ratio):
            return True
    return False


def _is_sector_only_text_op(op: dict[str, Any]) -> bool:
    if _coerce_str(op.get("fund_name")) or _coerce_str(op.get("fund_code")):
        return False
    sector = _coerce_str(op.get("sector"))
    if not sector:
        return False
    if op.get("action") in {"观望", ""}:
        return False
    return bool(_extract_amount(op))


def _is_sector_alert_op(op: dict[str, Any]) -> bool:
    """Blogger sector caution (观望): not a trade, but worth recording and notifying."""
    if op.get("action") != "观望":
        return False
    sector = _coerce_str(op.get("sector"))
    if not sector:
        return False
    if _coerce_str(op.get("fund_code")):
        return False
    name = _coerce_str(op.get("fund_name"))
    if name and _is_real_fund_op(op):
        return False
    return bool(_coerce_str(op.get("reason")) or _extract_amount(op))


def _normalize_raw_op(op: dict[str, Any], default_source: str = "text") -> dict[str, Any]:
    out = dict(op)
    original_action = _coerce_str(op.get("action"))
    fund_name = _coerce_str(op.get("fund_name"))
    if not fund_name:
        fund_name = _coerce_str(op.get("target"))
    out["fund_name"] = fund_name
    out["fund_code"] = _coerce_str(op.get("fund_code"))
    out["action"] = _infer_action(op)
    amount = _extract_amount(out)
    if amount:
        out["amount_or_ratio"] = amount
    out["_planting_hint"] = original_action == "种植" and not _coerce_str(op.get("fund_name"))
    out["_sector_only"] = _is_sector_only_text_op(out)
    out["_sector_alert"] = _is_sector_alert_op(out)
    if not out.get("source"):
        out["source"] = default_source
    return out


def _ops_match(text_op: dict[str, Any], image_op: dict[str, Any]) -> bool:
    text_code = _coerce_str(text_op.get("fund_code"))
    image_code = _coerce_str(image_op.get("fund_code"))
    if text_code and image_code and text_code == image_code:
        return True

    text_amount = _extract_amount(text_op)
    image_amount = _extract_amount(image_op)
    same_side = _action_side(text_op["action"]) == _action_side(image_op["action"])
    if image_code and text_amount and image_amount and _amounts_match(text_amount, image_amount):
        return same_side
    if text_amount and image_amount and _amounts_match(text_amount, image_amount):
        return same_side

    text_name = _coerce_str(text_op.get("fund_name"))
    text_sector = _coerce_str(text_op.get("sector"))
    image_name = _coerce_str(image_op.get("fund_name"))
    if text_name and image_name and _names_match(text_name, image_name):
        return same_side
    if (text_op.get("_sector_only") or (not text_name and text_sector)) and _is_real_fund_op(image_op):
        if text_amount and image_amount and _amounts_match(text_amount, image_amount):
            return same_side
    return False


def _merge_pair(text_op: dict[str, Any], image_op: dict[str, Any]) -> dict[str, Any]:
    merged = dict(image_op)
    image_code = _coerce_str(image_op.get("fund_code"))
    image_name = _coerce_str(image_op.get("fund_name"))
    text_name = _coerce_str(text_op.get("fund_name"))

    if image_code:
        merged["fund_code"] = image_code
        merged["fund_name"] = image_name or text_name
    else:
        merged["fund_name"] = image_name or text_name

    merged["action"] = _prefer_action(text_op["action"], image_op["action"])
    merged["amount_or_ratio"] = _extract_amount(text_op) or _extract_amount(image_op)
    if text_op.get("sector"):
        merged["sector"] = text_op["sector"]
    if text_op.get("reason"):
        merged["reason"] = text_op["reason"]
    merged["confidence"] = max(
        float(text_op.get("confidence", 0.7)),
        float(image_op.get("confidence", 0.9)),
    )
    merged["source"] = "merged"
    merged.pop("_planting_hint", None)
    merged.pop("_sector_only", None)
    return merged


def _is_valid_op(op: dict[str, Any]) -> bool:
    if op.get("_planting_hint"):
        return False
    if op.get("_sector_alert"):
        return True
    name = _coerce_str(op.get("fund_name"))
    if _looks_like_sector_alias(name) and not _coerce_str(op.get("fund_code")) and not _extract_amount(op):
        return False
    if op.get("_sector_only"):
        return True
    if name or _coerce_str(op.get("fund_code")):
        if op["action"] == "观望" and not _coerce_str(op.get("fund_code")):
            return bool(name)
        return op["action"] != "观望" or bool(_coerce_str(op.get("fund_code")))
    return False


def _dedupe_merged(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_codes: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for op in ops:
        code = _coerce_str(op.get("fund_code"))
        if code:
            if code in seen_codes:
                continue
            seen_codes.add(code)
            result.append(op)
            continue
        key = (normalize_fund_name(_coerce_str(op.get("fund_name"))), op.get("action", ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        result.append(op)
    return result


def _filter_valid_ops(ops: list[dict[str, Any]], default_source: str = "text") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for op in ops:
        normalized = _normalize_raw_op(op, default_source=default_source)
        if _is_valid_op(normalized):
            result.append(normalized)
    return result


def _merge_operations(text_ops: list[dict[str, Any]], image_ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    texts = _filter_valid_ops(text_ops, default_source="text")
    images = _filter_valid_ops(image_ops, default_source="image")

    merged: list[dict[str, Any]] = []
    used_text: set[int] = set()
    used_image: set[int] = set()

    for image_index, image_op in enumerate(images):
        if image_op.get("_planting_hint"):
            used_image.add(image_index)
            continue

        matched_text_index: int | None = None
        for text_index, text_op in enumerate(texts):
            if text_index in used_text:
                continue
            if _ops_match(text_op, image_op):
                matched_text_index = text_index
                break

        if matched_text_index is not None:
            merged.append(_merge_pair(texts[matched_text_index], image_op))
            used_text.add(matched_text_index)
            used_image.add(image_index)
        else:
            image_op = dict(image_op)
            image_op.pop("_planting_hint", None)
            image_op.pop("_sector_only", None)
            merged.append(image_op)
            used_image.add(image_index)

    for text_index, text_op in enumerate(texts):
        if text_index not in used_text:
            if text_op.get("_sector_only"):
                continue
            text_op = dict(text_op)
            text_op.pop("_planting_hint", None)
            text_op.pop("_sector_only", None)
            merged.append(text_op)

    return _drop_sector_alias_duplicates(_dedupe_merged(merged))


def _to_parsed_operation(
    raw: dict[str, Any],
    resolver: FundResolver,
    settings: Settings,
) -> ParsedOperation:
    action = _infer_action(raw)
    if action not in ACTIONS:
        action = "观望"
    fund_name = _coerce_str(raw.get("fund_name"))
    fund_code = _coerce_str(raw.get("fund_code"))
    sector = _coerce_str(raw.get("sector"))
    source = _coerce_str(raw.get("source")) or "text"
    confidence = float(raw.get("confidence", 0.7))

    if raw.get("_sector_alert") or (
        action == "观望" and sector and not fund_code and not (fund_name and _is_real_fund_op(raw))
    ):
        display = sector or fund_name
        return ParsedOperation(
            action="观望",
            fund_code="",
            fund_name=display,
            fund_name_raw=display,
            fund_code_source="",
            sector=sector,
            amount_or_ratio=_extract_amount(raw),
            reason=_coerce_str(raw.get("reason")),
            confidence=confidence,
            source=source,
            code_candidates=[],
        )

    resolve = resolver.resolve(fund_name, fund_code)
    if resolve.unique_match and resolve.fund_code_source == "search":
        confidence = max(confidence, 0.88)
    elif resolve.fund_code_source == "ocr":
        confidence = max(confidence, 0.9)
    elif resolve.candidates and not resolve.unique_match:
        confidence = min(confidence, 0.75)

    route = "auto"
    if confidence < settings.confidence_review_threshold:
        route = "manual"
    elif confidence < settings.confidence_auto_threshold or (
        resolve.candidates and not resolve.unique_match
    ):
        route = "review"
    elif not resolve.resolved and fund_name:
        route = "review"

    if route == "manual":
        confidence = min(confidence, settings.confidence_review_threshold - 0.01)

    return ParsedOperation(
        action=action,
        fund_code=resolve.fund_code,
        fund_name=resolve.fund_name or fund_name,
        fund_name_raw=resolve.fund_name_raw or fund_name,
        fund_code_source=resolve.fund_code_source,
        sector=sector,
        amount_or_ratio=_extract_amount(raw),
        reason=_coerce_str(raw.get("reason")),
        confidence=confidence,
        source=source,
        code_candidates=resolve.candidates,
    )


class ParsePipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = LLMExtractor(settings)
        self.resolver = FundResolver(settings.cache_dir)

    def parse_article(self, article: ArticleItem) -> ParseResult:
        article = enrich_article_images(article)
        image_data = self.llm.extract_from_image_urls(article.image_urls)
        text_data = self.llm.extract_from_text(
            article.title, article.content_text, image_data
        )
        analysis_data = self.llm.extract_analysis_from_text(
            article.title, article.content_text, image_data
        )
        risk_data = self.llm.extract_risk_alerts_from_text(
            article.title, article.content_text, image_data
        )
        text_ops = _filter_analytical_text_operations(
            text_data.get("operations", []),
            image_data.get("operations", []),
        )
        merged = _merge_operations(text_ops, image_data.get("operations", []))
        merged = _enrich_fund_ops_from_annotations(
            merged, analysis_data.get("annotations", [])
        )
        merged = _enrich_fund_ops_from_text_analysis(
            merged, text_data.get("operations", [])
        )
        merged = _append_risk_alerts_to_merged(
            merged, risk_data.get("risk_alerts", [])
        )
        operations = _drop_unresolved_sector_aliases([
            _to_parsed_operation(item, self.resolver, self.settings) for item in merged
        ])
        raw_json = {
            "text": text_data,
            "image": image_data,
            "analysis": analysis_data,
            "risk": risk_data,
            "merged": _sanitize_merged_ops(merged),
        }
        return ParseResult(article=article, operations=operations, raw_json=raw_json)

    def should_auto_store(self, op: ParsedOperation) -> bool:
        if self.is_sector_alert(op):
            return False
        if op.confidence < self.settings.confidence_auto_threshold:
            return False
        if op.code_candidates and not op.fund_code:
            return False
        if not op.fund_name:
            return False
        return bool(op.fund_code) or op.fund_code_source == "search"

    def should_review(self, op: ParsedOperation) -> bool:
        if self.is_sector_alert(op):
            return False
        if not op.fund_name:
            return False
        if self.should_auto_store(op):
            return False
        return op.confidence >= self.settings.confidence_review_threshold or bool(
            op.code_candidates
        )

    @staticmethod
    def is_sector_alert(op: ParsedOperation) -> bool:
        return op.action == "观望" and bool(op.sector) and not op.fund_code

    def should_save_sector_alert(self, op: ParsedOperation) -> bool:
        return self.is_sector_alert(op) and bool(op.reason or op.amount_or_ratio)
