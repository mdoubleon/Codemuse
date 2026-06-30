"""保存 Runtime 运行状态，包括消息列表、待审批调用和当前阶段。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolCall


@dataclass
class QueuedMessage:
    """表示等待 Web 会话 worker 处理的一条用户消息。"""
    text: str
    delivery: str = "follow_up"


@dataclass
class AgentState:
    """保存单个 Agent 会话的运行状态，包括消息、阶段和待处理工具调用。"""
    session_id: str
    system_prompt: str
    messages: list[ChatMessage] = field(default_factory=list)
    pending_tool_calls: list[ToolCall] = field(default_factory=list)
    pending_plan_token: str | None = None
    queued_messages: list[QueuedMessage] = field(default_factory=list)
    memory_context: dict[str, Any] = field(default_factory=dict)
    turn_id: int = 0
    phase: str = "idle"
    is_running: bool = False
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """把 AgentState 转成可写入文件或 API 响应的字典。"""
        return {
            "session_id": self.session_id,
            "system_prompt": self.system_prompt,
            "messages": [message.to_dict() for message in self.messages],
            "pending_tool_calls": [call.to_dict() for call in self.pending_tool_calls],
            "pending_plan_token": self.pending_plan_token,
            "queued_messages": [message.__dict__ for message in self.queued_messages],
            "memory_context": self.memory_context,
            "turn_id": self.turn_id,
            "phase": self.phase,
            "is_running": self.is_running,
            "error_message": self.error_message,
        }
