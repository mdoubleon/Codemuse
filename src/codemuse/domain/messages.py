"""定义对话消息结构：文本片段、消息角色和消息序列化。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from codemuse.domain.tools import ToolCall

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class TextPart:
    """表示一段纯文本消息内容，是 ChatMessage.content 的最小单元。"""
    text: str
    type: str = "text"

    def to_dict(self) -> dict[str, Any]:
        """把 TextPart 转成可写入文件或 API 响应的字典。"""
        return {"type": self.type, "text": self.text}

@dataclass
class ChatMessage:
    """表示一条对话消息，同时支持系统、用户、助手和工具角色。"""
    role: Role
    content: list[TextPart] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def text(cls, role: Role, text: str) -> "ChatMessage":
        """便捷创建只包含一段文本的 ChatMessage。"""
        return cls(role=role, content=[TextPart(text=text)])

    def text_content(self) -> str:
        """把 ChatMessage.content 中的所有 TextPart 合并成一段纯文本。"""
        return "\n".join(part.text for part in self.content if part.text)

    def to_dict(self) -> dict[str, Any]:
        """把 ChatMessage 转成可写入文件或 API 响应的字典。"""
        return {
            "role": self.role,
            "content": [part.to_dict() for part in self.content],
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatMessage":
        """把字典里的字段校正并恢复成 ChatMessage 对象。"""
        return cls(
            role=payload["role"],
            content=[TextPart(text=str(part.get("text", ""))) for part in payload.get("content", [])],
            tool_call_id=payload.get("tool_call_id"),
            tool_name=payload.get("tool_name"),
            tool_calls=[ToolCall.from_dict(item) for item in payload.get("tool_calls", [])],
            metadata=dict(payload.get("metadata") or {}),
            timestamp=float(payload.get("timestamp") or time.time()),
        )
