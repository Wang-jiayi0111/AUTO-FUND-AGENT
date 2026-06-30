from __future__ import annotations

from src.models import ArticleItem, ParsedOperation


def format_sector_risk_markdown(
    blogger_name: str,
    article: ArticleItem,
    alerts: list[ParsedOperation],
) -> str:
    lines = [
        "**⚠️ 板块风险提示（非操作建议）**",
        f"博主：{blogger_name}",
        f"文章：{article.title}",
        "",
    ]
    for op in alerts:
        detail = op.reason or op.amount_or_ratio or "谨慎/观望"
        lines.append(f"- **{op.sector or op.fund_name}**：{detail}")
    lines.append("")
    lines.append(f"[查看原文]({article.url})")
    return "\n".join(lines)
