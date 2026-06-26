from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

import httpx

from src.config import get_settings, llm_chat_completions_url
from src.ingest.rss_poller import poll_rss
from src.parse.fund_resolver import FundResolver
from src.store.feishu import FeishuStore


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _missing(value: str) -> bool:
    return not value or not value.strip()


def check_env() -> list[CheckResult]:
    settings = get_settings()
    results: list[CheckResult] = []

    rss_vars = [b.rss_url for b in settings.bloggers]
    rss_ok = all(not _missing(u) for u in rss_vars)
    results.append(
        CheckResult(
            "公众号 RSS (4)",
            rss_ok,
            "全部已配置" if rss_ok else f"已配置 {sum(1 for u in rss_vars if u)}/4",
        )
    )

    feishu_keys = [
        settings.feishu_app_id,
        settings.feishu_app_secret,
        settings.feishu_app_token,
        *settings.feishu_tables.values(),
    ]
    feishu_ok = all(not _missing(k) for k in feishu_keys)
    results.append(
        CheckResult(
            "飞书 Open API",
            feishu_ok,
            "全部已配置" if feishu_ok else "缺少 app_id / secret / token / table_id",
        )
    )

    wecom_ok = not _missing(settings.wecom_webhook_url)
    results.append(
        CheckResult(
            "企业微信 Webhook",
            wecom_ok,
            "已配置" if wecom_ok else "未配置 WECOM_WEBHOOK_URL",
        )
    )

    llm_ok = not _missing(settings.llm_api_key)
    results.append(
        CheckResult(
            "LLM API Key",
            llm_ok,
            "已配置" if llm_ok else "未配置 LLM_API_KEY",
        )
    )

    base_ok = not _missing(settings.feishu_base_url)
    results.append(
        CheckResult(
            "飞书表格链接 (FEISHU_BASE_URL)",
            base_ok,
            "已配置（待确认链接可用）" if base_ok else "建议配置，用于生成待确认直达链接",
        )
    )
    return results


def check_eastmoney() -> CheckResult:
    try:
        resolver = FundResolver(get_settings().cache_dir)
        items = resolver.search("华夏成长")
        return CheckResult(
            "东方财富基金搜索 API",
            len(items) > 0,
            f"返回 {len(items)} 条候选" if items else "无结果，请检查网络",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult("东方财富基金搜索 API", False, str(exc))


def check_rss() -> list[CheckResult]:
    settings = get_settings()
    results: list[CheckResult] = []
    for blogger in settings.bloggers:
        if _missing(blogger.rss_url):
            results.append(CheckResult(f"RSS · {blogger.name}", False, "未配置 URL"))
            continue
        try:
            articles = poll_rss(blogger, seen_guids=[])
            results.append(
                CheckResult(
                    f"RSS · {blogger.name}",
                    True,
                    f"可访问，当前 {len(articles)} 篇待处理文章",
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(f"RSS · {blogger.name}", False, str(exc)))
    return results


def check_feishu_api() -> CheckResult:
    settings = get_settings()
    if _missing(settings.feishu_app_id) or _missing(settings.feishu_app_secret):
        return CheckResult("飞书 API 连通", False, "缺少 app_id 或 app_secret")
    try:
        store = FeishuStore(settings)
        store._access_token()
        return CheckResult("飞书 API 连通", True, "tenant_access_token 获取成功")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("飞书 API 连通", False, str(exc))


def check_wecom(live: bool) -> CheckResult:
    settings = get_settings()
    if _missing(settings.wecom_webhook_url):
        return CheckResult("企业微信推送", False, "未配置 Webhook")
    if not live:
        return CheckResult("企业微信推送", True, "URL 已配置（加 --live 发送测试消息）")
    try:
        payload = {"msgtype": "text", "text": {"content": "AUTO-FUND-AGENT 配置测试"}}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(settings.wecom_webhook_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        ok = data.get("errcode") == 0
        return CheckResult("企业微信推送", ok, json.dumps(data, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        return CheckResult("企业微信推送", False, str(exc))


def check_llm(live: bool) -> CheckResult:
    settings = get_settings()
    if _missing(settings.llm_api_key):
        return CheckResult("LLM API", False, "未配置 LLM_API_KEY")
    if not live:
        return CheckResult("LLM API", True, "Key 已配置（加 --live 发送测试请求）")
    try:
        url = llm_chat_completions_url(settings.llm_base_url)
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
        payload = {
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": "回复 OK"}],
            "max_tokens": 5,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        return CheckResult("LLM API", True, "连通正常")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("LLM API", False, str(exc))


def print_results(results: list[CheckResult]) -> int:
    failed = 0
    for item in results:
        mark = "OK" if item.ok else "FAIL"
        print(f"[{mark}] {item.name}: {item.detail}")
        if not item.ok:
            failed += 1
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Step 1 API configuration")
    parser.add_argument("--live", action="store_true", help="Send live WeCom/LLM test requests")
    args = parser.parse_args()

    print("=== 第一步：环境变量检查 ===")
    env_results = check_env()
    env_failed = print_results(env_results)

    print("\n=== 网络与服务检查 ===")
    network_results = [check_eastmoney()]
    network_results.extend(check_rss())

    settings = get_settings()
    if not _missing(settings.feishu_app_id):
        network_results.append(check_feishu_api())
    network_results.append(check_wecom(args.live))
    network_results.append(check_llm(args.live))

    network_failed = print_results(network_results)

    total_failed = env_failed + network_failed
    print()
    if total_failed == 0:
        print("第一步已完成，所有检查通过。")
    else:
        print(f"还有 {total_failed} 项未通过。请按 docs/API_SETUP.md 补齐 .env 后重试。")
        print("命令：python -m src.tools.check_setup")
    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
