from __future__ import annotations

import httpx


class WeComNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_markdown(self, content: str) -> None:
        if not self.webhook_url:
            return
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errcode") not in (0, None):
            raise RuntimeError(f"WeCom send failed: {data}")

    def send_text(self, content: str) -> None:
        if not self.webhook_url:
            return
        payload = {"msgtype": "text", "text": {"content": content}}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
