"""把会话消息和系统 prompt 保存为本地 JSON 记录。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.domain.messages import ChatMessage
from codemuse.runtime.state import QueuedMessage


@dataclass
class SessionRecord:
    """SessionRecord：表示一条可保存和恢复的持久化记录。"""
    session_id: str
    system_prompt: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[ChatMessage] = field(default_factory=list)
    parent_session_id: str | None = None
    root_session_id: str | None = None
    depth: int = 0
    forked_at_message: int | None = None
    queued_messages: list[QueuedMessage] = field(default_factory=list)
    active_head_id: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """规范化树关系，让旧版记录自动成为根节点。"""
        if not self.root_session_id:
            self.root_session_id = self.session_id
        if self.parent_session_id is None:
            self.depth = 0
        elif self.depth < 1:
            self.depth = 1

    def to_dict(self) -> dict[str, Any]:
        """把 SessionRecord 转成可写入文件或 API 响应的字典。"""
        return {
            "session_id": self.session_id,
            "system_prompt": self.system_prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [message.to_dict() for message in self.messages],
            "parent_session_id": self.parent_session_id,
            "root_session_id": self.root_session_id,
            "depth": self.depth,
            "forked_at_message": self.forked_at_message,
            "queued_messages": [message.__dict__ for message in self.queued_messages],
            "active_head_id": self.active_head_id,
            "turns": list(self.turns),
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
            parent_session_id=str(payload["parent_session_id"]) if payload.get("parent_session_id") else None,
            root_session_id=str(payload["root_session_id"]) if payload.get("root_session_id") else None,
            depth=max(0, int(payload.get("depth") or 0)),
            forked_at_message=int(payload["forked_at_message"]) if payload.get("forked_at_message") is not None else None,
            queued_messages=[QueuedMessage(text=str(item.get("text") or ""), delivery=str(item.get("delivery") or "follow_up")) for item in (payload.get("queued_messages") if isinstance(payload.get("queued_messages"), list) else []) if isinstance(item, dict) and str(item.get("text") or "").strip()],
            active_head_id=str(payload["active_head_id"]) if payload.get("active_head_id") else None,
            turns=[dict(item) for item in (payload.get("turns") if isinstance(payload.get("turns"), list) else []) if isinstance(item, dict)],
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

    def fork(self, parent_session_id: str) -> SessionRecord:
        """从父会话当前的消息快照创建可独立演进的子会话。"""
        parent = self.load(parent_session_id)
        child_id = str(uuid.uuid4())
        messages = [ChatMessage.from_dict(message.to_dict()) for message in parent.messages]
        return SessionRecord(
            session_id=child_id,
            system_prompt=parent.system_prompt,
            messages=messages,
            parent_session_id=parent.session_id,
            root_session_id=parent.root_session_id or parent.session_id,
            depth=parent.depth + 1,
            forked_at_message=len(messages),
            queued_messages=[QueuedMessage(item.text, item.delivery) for item in parent.queued_messages],
            active_head_id=parent.active_head_id,
            turns=[dict(item) for item in parent.turns],
        )

    def fork_from_head(self, parent_session_id: str, head_id: str) -> SessionRecord:
        """Fork a session from a persisted turn head."""
        parent = self.load(parent_session_id)
        node = next((item for item in parent.turns if item.get("turn_node_id") == head_id), None)
        if node is None:
            raise ValueError(f"Unknown turn head: {head_id}")
        message_count = max(0, min(len(parent.messages), int(node.get("message_count") or 0)))
        child = self.fork(parent_session_id)
        child.messages = [ChatMessage.from_dict(message.to_dict()) for message in parent.messages[:message_count]]
        child.turns = [dict(item) for item in parent.turns if float(item.get("started_at") or 0) <= float(node.get("started_at") or 0)]
        child.active_head_id = head_id
        child.forked_at_message = message_count
        return child

    def set_active_head(self, session_id: str, head_id: str) -> SessionRecord:
        """Navigate a session to a persisted turn head and save the view."""
        record = self.load(session_id)
        node = next((item for item in record.turns if item.get("turn_node_id") == head_id), None)
        if node is None:
            raise ValueError(f"Unknown turn head: {head_id}")
        message_count = max(0, min(len(record.messages), int(node.get("message_count") or 0)))
        record.messages = [ChatMessage.from_dict(message.to_dict()) for message in record.messages[:message_count]]
        record.active_head_id = head_id
        self.save(record)
        return record

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

    def list_tree(self) -> list[dict[str, Any]]:
        """把持久化会话列成经过校验的嵌套森林。"""
        return build_session_tree([record.to_dict() for record in self.list()])


def build_session_tree(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """构建会话森林，孤儿节点或损坏的树关系仍作为根节点保留。"""
    nodes = {str(item["session_id"]): {**item, "children": []} for item in sessions}
    roots: list[dict[str, Any]] = []
    for item in sessions:
        node = nodes[str(item["session_id"])]
        parent_id = str(item.get("parent_session_id") or "")
        parent = nodes.get(parent_id)
        same_tree = parent and parent.get("root_session_id") == item.get("root_session_id")
        descends = parent and int(parent.get("depth") or 0) < int(item.get("depth") or 0)
        if parent and parent_id != item["session_id"] and same_tree and descends:
            parent["children"].append(node)
        else:
            roots.append(node)
    _sort_tree(roots)
    return roots


def _sort_tree(nodes: list[dict[str, Any]]) -> None:
    nodes.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    for node in nodes:
        _sort_tree(node["children"])
