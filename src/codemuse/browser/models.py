"""Serializable models for the bounded static browser."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrowserLink:
    ref: str
    text: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "text": self.text, "url": self.url}


@dataclass
class BrowserSnapshot:
    url: str
    text: str
    title: str = ""
    links: list[BrowserLink] = field(default_factory=list)
    status_code: int = 0
    truncated: bool = False
    executed_javascript: bool = False
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "links": [link.to_dict() for link in self.links],
            "status_code": self.status_code,
            "truncated": self.truncated,
            "executed_javascript": False,
            "captured_at": self.captured_at,
        }


@dataclass
class BrowserTab:
    tab_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str = ""
    history: list[BrowserSnapshot] = field(default_factory=list)
    history_index: int = -1

    @property
    def snapshot(self) -> BrowserSnapshot | None:
        return self.history[self.history_index] if 0 <= self.history_index < len(self.history) else None

    def to_dict(self) -> dict[str, Any]:
        snapshot = self.snapshot
        return {"tab_id": self.tab_id, "label": self.label, "url": snapshot.url if snapshot else "", "title": snapshot.title if snapshot else "", "active_history_index": self.history_index}
