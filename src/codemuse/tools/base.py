"""定义工具基类和工具结果到 tool message 的转换方法。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.domain.messages import ChatMessage, TextPart
from codemuse.domain.tools import ToolResult as DomainToolResult
from codemuse.domain.tools import ToolSpec


class ToolResult(DomainToolResult):
    """承载工具执行后的观察结果，后续会回写给模型。"""
    def as_chat_message(self) -> ChatMessage:
        """将工具结果转换为 role=tool 的 ChatMessage。"""
        return ChatMessage(
            role="tool",
            content=[TextPart(text=self.content)],
            tool_name=self.tool_name,
            tool_call_id=self.tool_call_id or None,
            metadata={"details": self.details, "success": self.success, "is_error": self.is_error},
        )


class BaseTool:
    """所有本地工具的基类，统一要求 spec 和 execute 两个接口。"""
    def __init__(self, workspace: Path) -> None:
        """保存工具只能访问的 workspace 根目录。"""
        self.workspace = workspace.resolve()

    @property
    def spec(self) -> ToolSpec:
        """抽象属性：子类必须返回自己的工具名、参数 schema、权限域和副作用声明。"""
        raise NotImplementedError

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """抽象执行接口，具体工具必须在子类里实现。"""
        raise NotImplementedError

    def resolve_workspace_path(self, raw_path: str) -> Path:
        """把工具参数里的路径限制在 workspace 内，防止工具越权读取或写入外部文件。"""
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        if self.workspace not in resolved.parents and resolved != self.workspace:
            raise PermissionError(f"Path is outside workspace: {raw_path}")
        return resolved
