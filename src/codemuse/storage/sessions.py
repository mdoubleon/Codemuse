"""把会话消息和系统 prompt 保存为本地 JSON 记录。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.domain.messages import ChatMessage


@dataclass
class SessionRecord:
    """SessionRecord：表示一条可保存和恢复的持久化记录。"""
    session_id: str
    system_prompt: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[ChatMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """把 SessionRecord 转成可写入文件或 API 响应的字典。"""
        return {
            "session_id": self.session_id,
            "system_prompt": self.system_prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionRecord":
        """把字典里的字段校正并恢复成 SessionRecord 对象。"""
        return cls(
            session_id=str(payload["session_id"]),
            system_prompt=str(payload.get("system_prompt") or ""),
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
            messages=[ChatMessage.from_dict(item) for item in payload.get("messages", [])],
        )


class SessionStore:
    """SessionStore：封装该类数据的本地持久化读写。"""
    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, system_prompt: str) -> SessionRecord:
        """创建一条新的领域记录或运行结果。"""
        return SessionRecord(session_id=str(uuid.uuid4()), system_prompt=system_prompt)

    def save(self, record: SessionRecord) -> None:
        """将对象写入本地存储。"""
        record.updated_at = time.time()
        path = self.root / f"{record.session_id}.json"
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> SessionRecord:
        """按标识读取本地存储中的对象。"""
        path = self.root / f"{session_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")
        return SessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[SessionRecord]:
        """列出当前存储或目录中的对象。"""
        records: list[SessionRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                records.append(SessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                # 会话列表是给 CLI/SDK 展示用；坏文件跳过，避免一个损坏记录拖垮整个入口。
                continue
        return sorted(records, key=lambda item: item.updated_at, reverse=True)
