from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any

import httpx

from src.config import Settings, llm_chat_completions_url

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """你是基金操作信息提取助手。从给定的微信公众号文章正文中提取基金操作信息。

要求：
1. 只提取明确提到的基金操作，不要臆造
2. action 只能是：买入、卖出、加仓、减仓、定投、观望
3. fund_code 仅当正文或描述中明确出现6位数字代码时填写，否则留空
4. 禁止编造基金代码
5. 返回严格 JSON，格式如下：
{
  "operations": [
    {
      "action": "加仓",
      "fund_code": "",
      "fund_name": "华夏成长",
      "sector": "科技",
      "amount_or_ratio": "10%",
      "reason": "政策利好",
      "confidence": 0.9,
      "source": "text"
    }
  ]
}
如果没有基金操作，返回 {"operations": []}

补充规则（重要）：
6. 博主口中的板块/主题简称（包括但不限于 CPO、上海金、半导体、黄金、人工智能、新能源、光伏、储能、医药、白酒、消费、红利、微盘、债基、人工智能、芯片、光模块、机器人、卫星等）不是基金产品名；这类词填入 sector，fund_name 留空
7. 只有正文明确提到具体基金产品（如「富国上海金ETF联接」「华泰柏瑞质量成长混合」）或出现 6 位基金代码时，才填写 fund_name
8. 同一笔操作不要既填 sector 简称又填对应基金全名；若已有截图/代码能确定基金，正文里只保留 sector 即可
9. 博主对某板块表达谨慎/不建议操作时：action 填「观望」，sector 填板块名，reason 填原话，fund_name 留空
10. 不少博主正文是对截图操作的复盘分析，真实成交在配图里。若用户消息已给出「截图已识别的操作」，正文 operations 应返回 []，除非正文有截图未体现的「观望/风险提示」（action=观望，填 sector 和 reason）
11. amount_or_ratio 必须是可解析的具体数字金额（如 1万、5000元）；禁止填写「一点」「重仓」「调仓」「2w和1W」等模糊词——这类表述只写在 reason 里
12. 同一 sector 在同一篇文章只保留一条分析性记录，不要因重复段落拆成多条
13. 正文分析某板块时只填 sector，fund_name 留空；不要臆造具体基金产品名
"""

ANALYSIS_PROMPT = """你是基金文章分析助手。博主配图里已有具体基金成交截图，正文是对这些操作的板块复盘。

请从正文提取各板块的 sector（板块/主题）和 reason（分析理由），用于补充截图操作。

返回严格 JSON：
{
  "annotations": [
    {
      "sector": "半导体",
      "reason": "趁回调定投，存储短缺、产能扩建，业绩确定",
      "keywords": ["半导体", "芯片", "存储"]
    }
  ]
}

规则：
1. sector 填板块/主题名（如半导体、CPO、中小盘、海外、航天、创新药）
2. reason 填正文原话或 faithful 摘要，保留博主观点
3. keywords 填 sector 本身 + 可用于匹配基金名的词（如「多策略」对应中小盘类、「半导体ETF」对应半导体）
4. 同一 sector 只保留一条，合并重复段落
5. 只提取正文明确提到的板块，不要臆造截图里没有对应分析的板块
6. 若正文几乎无实质分析，返回 {"annotations": []}
"""

RISK_ALERT_PROMPT = """你是基金风险提示提取助手。从公众号正文中提取博主对板块的谨慎/观望/风险观点（不是买入卖出等具体操作）。

返回严格 JSON：
{
  "risk_alerts": [
    {
      "sector": "有色",
      "reason": "波动比较大，不建议贸然去抄底",
      "amount_or_ratio": "20万"
    }
  ]
}

规则：
1. 只提取明确表达谨慎、观望、不建议买入、风险提示、暂时回避的板块
2. sector 填板块/主题名（如有色、黄金、CPO、半导体、军工、白酒）
3. reason 填正文原话或 faithful 摘要
4. amount_or_ratio 仅当正文提到具体金额/仓位时填写，否则留空
5. 同一 sector 只保留一条
6. 不要把正常的加仓/定投/买入分析当作风险提示
7. 若全文无风险提示，返回 {"risk_alerts": []}
"""

VISION_PROMPT = """从这张基金相关截图中提取基金操作信息。

要求：
1. action 只能是：买入、卖出、加仓、减仓、定投、观望（截图里「买入确认中」写买入，「卖出确认中」写卖出）
2. fund_code 仅当明确看到6位数字代码时填写，否则留空
3. amount 用字符串并带单位（如 10,000.00元），shares 用字符串并带「份」
4. 禁止编造基金代码
5. 一张截图里可能有多笔买卖记录（列表/滚动截图），必须全部提取，不要只取第一条
6. 返回严格 JSON：{"operations": [...]}，每条必须包含 action 和 fund_name 字段"""


def filter_trade_image_urls(image_urls: list[str]) -> list[str]:
    """Skip decorative GIF headers; keep trade screenshot candidates."""
    filtered: list[str] = []
    for url in image_urls:
        path = url.lower().split("?", 1)[0]
        if path.endswith(".gif") or "/mmbiz_gif/" in path:
            continue
        filtered.append(url)
    return filtered


class LLMExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _chat(self, messages: list[dict[str, Any]], model: str | None = None) -> str:
        model = model or self.settings.llm_model
        url = llm_chat_completions_url(self.settings.llm_base_url)
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        timeout = httpx.Timeout(
            self.settings.llm_timeout_seconds,
            connect=30.0,
        )
        last_error: Exception | None = None
        for attempt in range(1, self.settings.llm_max_retries + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
                wait_s = min(2 ** attempt, 8)
                logger.warning(
                    "LLM request timeout (attempt %d/%d), retry in %ds",
                    attempt,
                    self.settings.llm_max_retries,
                    wait_s,
                )
                time.sleep(wait_s)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    break
                wait_s = min(2 ** attempt, 8)
                logger.warning(
                    "LLM request failed (attempt %d/%d): %s",
                    attempt,
                    self.settings.llm_max_retries,
                    exc,
                )
                time.sleep(wait_s)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.S)
            if match:
                return json.loads(match.group(0))
            raise

    @staticmethod
    def _format_image_hints(image_data: dict[str, Any] | None) -> str:
        if not image_data:
            return ""
        lines: list[str] = []
        for op in image_data.get("operations", []):
            name = str(op.get("fund_name") or "").strip()
            if not name:
                continue
            action = str(op.get("action") or op.get("type") or "").strip()
            amount = str(
                op.get("amount_or_ratio") or op.get("amount") or op.get("shares") or ""
            ).strip()
            lines.append(f"- {action} {name} {amount}".strip())
        if not lines:
            return ""
        return (
            "【截图已识别的操作（以此为准，正文勿重复拆条）】\n"
            + "\n".join(lines)
            + "\n\n"
        )

    def extract_from_text(
        self,
        title: str,
        content: str,
        image_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_api_key:
            return {"operations": []}
        hints = self._format_image_hints(image_data)
        user_content = f"{hints}标题：{title}\n\n正文：{content[:12000]}"
        raw = self._chat(
            [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        return self._parse_json(raw)

    def extract_analysis_from_text(
        self,
        title: str,
        content: str,
        image_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract sector/reason annotations from analytical body text."""
        if not self.settings.llm_api_key:
            return {"annotations": []}
        fund_lines: list[str] = []
        for op in (image_data or {}).get("operations", []):
            name = str(op.get("fund_name") or "").strip()
            if name:
                fund_lines.append(f"- {name}")
        funds_block = ""
        if fund_lines:
            funds_block = "【截图已识别的基金】\n" + "\n".join(fund_lines) + "\n\n"
        user_content = f"{funds_block}标题：{title}\n\n正文：{content[:12000]}"
        raw = self._chat(
            [
                {"role": "system", "content": ANALYSIS_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        data = self._parse_json(raw)
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return {"annotations": []}
        return {"annotations": annotations}

    def extract_risk_alerts_from_text(
        self,
        title: str,
        content: str,
        image_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract sector risk/caution views from body text (non-trade alerts)."""
        if not self.settings.llm_api_key:
            return {"risk_alerts": []}
        fund_lines: list[str] = []
        for op in (image_data or {}).get("operations", []):
            name = str(op.get("fund_name") or "").strip()
            if name:
                fund_lines.append(f"- {name}")
        funds_block = ""
        if fund_lines:
            funds_block = (
                "【截图已识别的基金成交（以下板块若仅有正常操作则不必重复作为风险提示）】\n"
                + "\n".join(fund_lines)
                + "\n\n"
            )
        user_content = f"{funds_block}标题：{title}\n\n正文：{content[:12000]}"
        raw = self._chat(
            [
                {"role": "system", "content": RISK_ALERT_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        data = self._parse_json(raw)
        alerts = data.get("risk_alerts", [])
        if not isinstance(alerts, list):
            return {"risk_alerts": []}
        return {"risk_alerts": alerts}

    def extract_from_image_url(self, image_url: str) -> dict[str, Any]:
        if not self.settings.llm_api_key:
            return {"operations": []}
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(image_url, headers={"User-Agent": "AUTO-FUND-AGENT/1.0"})
            resp.raise_for_status()
            media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            b64 = base64.b64encode(resp.content).decode("ascii")
        data_url = f"data:{media_type};base64,{b64}"
        raw = self._chat(
            [
                {"role": "system", "content": VISION_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请提取截图中的基金操作"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            model=self.settings.llm_vision_model,
        )
        return self._parse_json(raw)

    def extract_from_image_urls(
        self,
        image_urls: list[str],
        max_images: int | None = None,
    ) -> dict[str, Any]:
        limit = max_images if max_images is not None else self.settings.vision_max_images
        trade_urls = filter_trade_image_urls(image_urls)
        urls = trade_urls[:limit]
        if not urls:
            return {"operations": []}

        logger.info(
            "Vision: processing %d/%d images (skipped %d gif/decorative)",
            len(urls),
            len(image_urls),
            len(image_urls) - len(trade_urls),
        )

        merged: list[dict[str, Any]] = []
        for index, url in enumerate(urls, start=1):
            try:
                data = self.extract_from_image_url(url)
                ops = data.get("operations", [])
                merged.extend(ops)
                logger.info("Vision image %d/%d: %d operation(s)", index, len(urls), len(ops))
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("Vision image %d/%d failed: %s", index, len(urls), exc)
                continue
        return {"operations": merged}
