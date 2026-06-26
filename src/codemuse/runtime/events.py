"""定义给 CLI、Web 和 timeline 观察的 Agent 运行事件。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    """描述 Runtime 运行过程中可被 UI 或 timeline 观察的事件。"""
    type: str
    session_id: str
    turn_id: int | None = None
    phase: str | None = None
    message: str | None = None
    delta: str | None = None
    tool_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """把 AgentEvent 转成可写入文件或 API 响应的字典。"""
        return {
            "type": self.type,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "phase": self.phase,
            "message": self.message,
            "delta": self.delta,
            "tool_name": self.tool_name,
            "details": self.details,
            "is_error": self.is_error,
            "timestamp": self.timestamp,
        }
