"""定义会话检查点记录，用于 rewind 恢复消息状态。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from codemuse.domain.messages import ChatMessage


@dataclass
class CheckpointRecord:
    """Agent 会话检查点。

    这一层只描述“检查点是什么”，不负责写文件，也不负责执行 rewind。
    持久化由 storage 层处理，创建、恢复和副作用工具前的自动 checkpoint 由 runtime 层处理。
    """

    checkpoint_id: str
    session_id: str
    label: str
    turn_id: int
    messages: list[ChatMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """把 CheckpointRecord 转成可写入文件或 API 响应的字典。"""
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "label": self.label,
            "turn_id": self.turn_id,
            "messages": [message.to_dict() for message in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CheckpointRecord":
        """把字典里的字段校正并恢复成 CheckpointRecord 对象。"""
        return cls(
            checkpoint_id=str(payload["checkpoint_id"]),
            session_id=str(payload["session_id"]),
            label=str(payload.get("label") or "checkpoint"),
            turn_id=int(payload.get("turn_id") or 0),
            messages=[ChatMessage.from_dict(item) for item in payload.get("messages", [])],
            metadata=dict(payload.get("metadata") or {}),
            created_at=float(payload.get("created_at") or time.time()),
        )
