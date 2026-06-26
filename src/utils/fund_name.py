from __future__ import annotations

import re
import unicodedata


_SUFFIXES = ("混合", "A类", "C类", "A", "C", "基金")

# OCR/API naming drift: optional in one side but not the other.
_OPTIONAL_NAME_TOKENS = (
    "灵活配置",
    "发起式",
    "发起",
    "指数增强",
    "增强型",
    "增强",
    "精选",
    "优选",
)


def _clean_fund_text(name: str) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).strip()
    return re.sub(r"\s+", "", text)


def clean_fund_text(name: str) -> str:
    return _clean_fund_text(name)


def normalize_fund_name(name: str) -> str:
    if not name:
        return ""
    text = _clean_fund_text(name)
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def fund_name_core(name: str) -> str:
    """Strip share-class suffixes and optional middle tokens for fuzzy compare."""
    text = normalize_fund_name(name)
    for token in _OPTIONAL_NAME_TOKENS:
        text = text.replace(token, "")
    return text.strip()


def fund_names_equivalent(left: str, right: str) -> bool:
    left_core = fund_name_core(left)
    right_core = fund_name_core(right)
    if not left_core or not right_core:
        return False
    if left_core == right_core:
        return True
    return left_core in right_core or right_core in left_core


def fund_name_match_score(raw: str, candidate: str) -> float:
    if not raw or not candidate:
        return 0.0
    if raw == candidate:
        return 1.0
    if fund_names_equivalent(raw, candidate):
        return 0.95

    share_class = fund_share_class_hint(raw)
    if share_class and not candidate_matches_share_class(candidate, share_class):
        return 0.0

    raw_core = fund_name_core(raw)
    cand_core = fund_name_core(candidate)
    if not raw_core or not cand_core:
        return 0.0
    if raw_core == cand_core:
        return 0.93
    if raw_core in cand_core or cand_core in raw_core:
        shorter = min(len(raw_core), len(cand_core))
        longer = max(len(raw_core), len(cand_core))
        return 0.85 + 0.08 * (shorter / longer)

    overlap = sum(1 for ch in raw_core if ch in cand_core)
    ratio = overlap / max(len(raw_core), len(cand_core))
    if ratio >= 0.75:
        return 0.7 * ratio
    return 0.0


def fund_search_queries(raw_name: str) -> list[str]:
    """Build ordered East Money search keys for OCR/API name drift."""
    base = _clean_fund_text(raw_name)
    if not base:
        return []

    stripped = base
    for token in _OPTIONAL_NAME_TOKENS:
        stripped = stripped.replace(token, "")

    normalized = normalize_fund_name(base)
    core = fund_name_core(base)

    queries: list[str] = []
    for candidate in (base, stripped, normalized, core):
        if candidate and candidate not in queries:
            queries.append(candidate)

    # Progressive shorten the core token (company + theme often enough).
    for length in (12, 10, 8, 6):
        if len(core) > length:
            short = core[:length]
            if short not in queries:
                queries.append(short)

    return queries


def is_valid_fund_code(code: str) -> bool:
    return bool(code and re.fullmatch(r"\d{6}", code.strip()))


def fund_share_class_hint(name: str) -> str | None:
    """Return A/C when the raw fund name indicates a share class."""
    if not name:
        return None
    text = unicodedata.normalize("NFKC", name).strip()
    text = re.sub(r"\s+", "", text)
    if re.search(r"(联接|混合)C类?$", text):
        return "C"
    if re.search(r"(联接|混合)A类?$", text):
        return "A"
    return None


def candidate_matches_share_class(candidate_name: str, share_class: str) -> bool:
    text = unicodedata.normalize("NFKC", candidate_name).strip()
    text = re.sub(r"\s+", "", text)
    if share_class == "C":
        return bool(re.search(r"(联接|混合)C类?$", text))
    if share_class == "A":
        return bool(re.search(r"(联接|混合)A类?$", text))
    return False
