"""把 Runtime 产生的 AgentEvent 追加为 JSONL，供后续回看。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from codemuse.runtime.events import AgentEvent


class TimelineStore:
    """TimelineStore：封装该类数据的本地持久化读写。"""
    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, event: AgentEvent) -> None:
        """将一条记录追加到当前存储。"""
        path = self._path(event.session_id)
        # timeline 用 JSONL 追加写入：一行就是一个事件，方便以后做流式读取和增量展示。
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def list(self, *, session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """列出当前存储或目录中的对象。"""
        paths = [self._path(session_id)] if session_id else sorted(self.root.glob("*.jsonl"))
        events: list[dict[str, Any]] = []
        for path in paths:
            if not path.exists():
                continue
            events.extend(self._read_path(path))
        events.sort(key=lambda item: (float(item.get("timestamp") or 0.0), int(item.get("timeline_index") or 0)))
        if limit >= 0:
            events = events[-limit:]
        return events

    def _read_path(self, path: Path) -> list[dict[str, Any]]:
        """读取内部数据并转换为当前模块需要的结构。"""
        records: list[dict[str, Any]] = []
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            payload.setdefault("session_id", path.stem)
            payload["timeline_index"] = index
            records.append(payload)
        return records

    def _path(self, session_id: str) -> Path:
        """根据标识计算本地存储路径。"""
        safe = _safe_session_id(session_id)
        return self.root / f"{safe}.jsonl"


def _safe_session_id(session_id: str) -> str:
    """生成安全可控的内部表示，避免路径或名称越界。"""
    value = str(session_id).strip()
    if not value or re.search(r"[^a-zA-Z0-9_-]", value):
        raise ValueError(f"Invalid session id for timeline path: {session_id}")
    return value
