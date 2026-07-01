from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.notify.wecom import WeComNotifier
from src.store.feishu import FeishuStore
from src.utils.fund_name import normalize_fund_name
from src.utils.log_setup import configure_logging
from src.utils.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)


def _field_text(record: dict, key: str) -> str:
    return FeishuStore._field_text(record, key)


def _field_url(record: dict, key: str) -> str:
    return FeishuStore._field_url(record, key)


def _match_focus(op: dict, focus_items: list[dict[str, str]], store: FeishuStore) -> bool:
    blogger = store.blogger_id_from_field(op, "blogger_id")
    code = _field_text(op, "fund_code")
    name = normalize_fund_name(_field_text(op, "fund_name"))
    for item in focus_items:
        if item["blogger_id"] != blogger:
            continue
        if item["fund_code"] and code and item["fund_code"] == code:
            return True
        if item["fund_name"] and name and item["fund_name"] == name:
            return True
    return False


def _is_sector_alert_record(record: dict) -> bool:
    action = _field_text(record, "action")
    status = _field_text(record, "status")
    return action == "观望" or status == "风险提示"


def build_digest(store: FeishuStore, since: datetime) -> str:
    follow_ids = store.get_active_follow_bloggers()
    focus_items = store.get_active_focus_items()
    name_map = store.get_blogger_name_map()
    operations = store.get_operations_since(since)
    pending = store.get_pending_reviews()
    articles = store.get_articles_since(since)

    sector_alerts: list[dict] = []
    focus_ops: list[dict] = []
    normal_ops: list[dict] = []
    bloggers_with_ops: set[str] = set()

    for op in operations:
        blogger_id = store.blogger_id_from_field(op, "blogger_id")
        if follow_ids and blogger_id not in follow_ids:
            continue
        if _is_sector_alert_record(op):
            sector_alerts.append(op)
            bloggers_with_ops.add(blogger_id)
            continue
        bloggers_with_ops.add(blogger_id)
        if _match_focus(op, focus_items, store):
            focus_ops.append(op)
        else:
            normal_ops.append(op)

    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    lines = [f"**【基金跟进提醒】{now.strftime('%Y-%m-%d')} 周{weekday}**", ""]

    if sector_alerts:
        lines.append("**⚠️ 板块风险提示（非操作建议）**")
        for op in sector_alerts:
            blogger_id = store.blogger_id_from_field(op, "blogger_id")
            blogger_name = name_map.get(blogger_id, blogger_id)
            sector = _field_text(op, "sector") or _field_text(op, "fund_name")
            lines.append(f"- {blogger_name} → {sector}")
            reason = _field_text(op, "reason")
            amount = _field_text(op, "amount_or_ratio")
            if reason:
                lines.append(f"  观点：{reason}")
            elif amount:
                lines.append(f"  提及：{amount}")
            url = _field_url(op, "article_url")
            if url:
                lines.append(f"  原文：{url}")
        lines.append("")

    if focus_ops:
        lines.append("**🔥 重点关注（需优先处理）**")
        for op in focus_ops:
            blogger_id = store.blogger_id_from_field(op, "blogger_id")
            blogger_name = name_map.get(blogger_id, blogger_id)
            fund_name = _field_text(op, "fund_name")
            fund_code = _field_text(op, "fund_code")
            code_part = f"({fund_code})" if fund_code else ""
            lines.append(
                f"- {blogger_name} → {_field_text(op, 'action')} | "
                f"{fund_name}{code_part} | {_field_text(op, 'sector')} | "
                f"{_field_text(op, 'amount_or_ratio')}"
            )
            reason = _field_text(op, "reason")
            if reason:
                lines.append(f"  理由：{reason}")
            url = _field_url(op, "article_url")
            if url:
                lines.append(f"  原文：{url}")
        lines.append("")

    lines.append("**📌 其他跟进博主**")
    if normal_ops:
        by_blogger: dict[str, list[dict]] = {}
        for op in normal_ops:
            by_blogger.setdefault(store.blogger_id_from_field(op, "blogger_id"), []).append(op)
        for blogger_id, ops in by_blogger.items():
            blogger_name = name_map.get(blogger_id, blogger_id)
            for op in ops:
                fund_name = _field_text(op, "fund_name")
                fund_code = _field_text(op, "fund_code")
                code_part = f"({fund_code})" if fund_code else ""
                lines.append(
                    f"- {blogger_name} → {_field_text(op, 'action')} | "
                    f"{fund_name}{code_part} | {_field_text(op, 'amount_or_ratio')}"
                )
    else:
        for blogger_id in sorted(follow_ids):
            if blogger_id not in bloggers_with_ops:
                blogger_name = name_map.get(blogger_id, blogger_id)
                lines.append(f"- {blogger_name} → 无新操作")

    if pending:
        lines.extend(["", "---", f"**待确认 {len(pending)} 条**"])
        for rec in pending[:5]:
            conf = _field_text(rec, "confidence")
            fund = _field_text(rec, "fund_name")
            link = store.record_link("pending_review", rec["record_id"])
            lines.append(f"- {fund}（置信度 {conf}）[打开飞书确认]({link})")

    article_bloggers = {store.blogger_id_from_field(rec, "blogger_id") for rec in articles}
    failed = [rec for rec in articles if _field_text(rec, "status") == "解析失败"]
    parsed = [
        rec for rec in articles
        if _field_text(rec, "status") in {"已解析", "无操作", "待确认"}
    ]
    lines.extend([
        "",
        "---",
        "**运行摘要**",
        f"- 今日发现文章：{len(articles)} 篇",
        f"- 成功处理文章：{len(parsed)} 篇",
        f"- 自动/风险入库操作：{len(operations)} 条",
        f"- 待确认：{len(pending)} 条",
        f"- 失败：{len(failed)} 篇",
    ])
    missing = sorted(follow_ids - article_bloggers) if follow_ids else []
    if missing:
        names = [name_map.get(blogger_id, blogger_id) for blogger_id in missing]
        lines.append(f"- 未发现当天文章：{'、'.join(names)}")
    if failed:
        titles = [_field_text(rec, "title") for rec in failed[:3]]
        lines.append(f"- 失败文章：{'；'.join(titles)}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send weekday fund digest via WeCom")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Send even on non-trading days")
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Append logs to this UTF-8 file (do not use shell >> redirect)",
    )
    args = parser.parse_args()

    configure_logging(log_file=args.log_file)

    settings = get_settings()

    if not args.force and not is_trading_day():
        logger.info("Not a trading day, skipping digest")
        return

    if not settings.feishu_app_id or not settings.feishu_app_token:
        logger.error("Feishu not configured")
        return

    store = FeishuStore(settings)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    content = build_digest(store, since)

    if args.dry_run:
        sys.stdout.buffer.write((content + "\n").encode("utf-8"))
        return

    notifier = WeComNotifier(settings.wecom_webhook_url)
    notifier.send_markdown(content)
    logger.info("Digest sent")


if __name__ == "__main__":
    main()
