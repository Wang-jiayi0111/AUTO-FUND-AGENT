from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def llm_chat_completions_url(base_url: str) -> str:
    """Build chat/completions URL; base_url may already end with /v1 (百炼 compatible-mode)."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


@dataclass(frozen=True)
class BloggerConfig:
    id: str
    name: str
    wechat_name: str
    rss_url: str


@dataclass(frozen=True)
class Settings:
    bloggers: list[BloggerConfig]
    feishu_app_id: str
    feishu_app_secret: str
    feishu_app_token: str
    feishu_tables: dict[str, str]
    wecom_webhook_url: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_vision_model: str
    llm_timeout_seconds: float
    llm_max_retries: int
    vision_max_images: int
    poll_interval_minutes: int
    digest_hour: int
    digest_minute: int
    confidence_auto_threshold: float
    confidence_review_threshold: float
    feishu_base_url: str
    cache_dir: Path


def _resolve_rss_url(env_key: str) -> str:
    """Read RSS URL; supports legacy FEEDDD_RSS_* variable names."""
    value = os.getenv(env_key, "").strip()
    if value:
        return value
    legacy_key = env_key.replace("RSS_", "FEEDDD_RSS_", 1)
    if legacy_key != env_key:
        return os.getenv(legacy_key, "").strip()
    return ""


def _load_bloggers() -> list[BloggerConfig]:
    path = ROOT / "config" / "bloggers.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    bloggers: list[BloggerConfig] = []
    for item in data.get("bloggers", []):
        env_key = item["rss_url_env"]
        rss_url = _resolve_rss_url(env_key)
        bloggers.append(
            BloggerConfig(
                id=item["id"],
                name=item["name"],
                wechat_name=item["wechat_name"],
                rss_url=rss_url,
            )
        )
    return bloggers


@lru_cache
def get_settings() -> Settings:
    tables = {
        "bloggers": os.getenv("FEISHU_TABLE_BLOGGERS", ""),
        "follow_list": os.getenv("FEISHU_TABLE_FOLLOW_LIST", ""),
        "focus_list": os.getenv("FEISHU_TABLE_FOCUS_LIST", ""),
        "operations": os.getenv("FEISHU_TABLE_OPERATIONS", ""),
        "articles": os.getenv("FEISHU_TABLE_ARTICLES", ""),
        "fund_mapping": os.getenv("FEISHU_TABLE_FUND_MAPPING", ""),
        "pending_review": os.getenv("FEISHU_TABLE_PENDING_REVIEW", ""),
    }
    return Settings(
        bloggers=_load_bloggers(),
        feishu_app_id=os.getenv("FEISHU_APP_ID", ""),
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        feishu_app_token=os.getenv("FEISHU_APP_TOKEN", ""),
        feishu_tables=tables,
        wecom_webhook_url=os.getenv("WECOM_WEBHOOK_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "",
        llm_base_url=os.getenv(
            "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        llm_model=os.getenv("LLM_MODEL", "qwen-plus"),
        llm_vision_model=os.getenv("LLM_VISION_MODEL", "qwen-vl-plus"),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "180")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        vision_max_images=int(os.getenv("VISION_MAX_IMAGES", "15")),
        poll_interval_minutes=int(os.getenv("POLL_INTERVAL_MINUTES", "30")),
        digest_hour=int(os.getenv("DIGEST_HOUR", "14")),
        digest_minute=int(os.getenv("DIGEST_MINUTE", "30")),
        confidence_auto_threshold=float(os.getenv("CONFIDENCE_AUTO_THRESHOLD", "0.85")),
        confidence_review_threshold=float(os.getenv("CONFIDENCE_REVIEW_THRESHOLD", "0.60")),
        feishu_base_url=os.getenv("FEISHU_BASE_URL", ""),
        cache_dir=ROOT / "data" / "cache",
    )
