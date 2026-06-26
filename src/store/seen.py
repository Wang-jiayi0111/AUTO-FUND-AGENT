from __future__ import annotations

import json
from pathlib import Path

from src.config import ROOT


class SeenStore:
    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "data" / "seen_guids.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def seen_for_blogger(self, blogger_id: str) -> set[str]:
        return set(self._data.get(blogger_id, []))

    def mark_seen(self, blogger_id: str, guid: str) -> None:
        items = self._data.setdefault(blogger_id, [])
        if guid not in items:
            items.append(guid)
            self._save()
