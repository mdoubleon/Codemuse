"""定义工具协议的核心数据：ToolSpec、ToolCall 和 ToolResult。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """描述一个工具的名称、说明、参数 schema、权限域和副作用标记。"""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    permission_domain: str = "read"
    sensitive: bool = False
    model_callable: bool = True
    side_effect: bool = False

    def to_dict(self) -> dict[str, Any]:
        """把 ToolSpec 转成可写入文件或 API 响应的字典。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "requires_confirmation": self.requires_confirmation,
            "permission_domain": self.permission_domain,
            "sensitive": self.sensitive,
            "model_callable": self.model_callable,
            "side_effect": self.side_effect,
        }


@dataclass
class ToolCall:
    """承载模型发起的一次工具调用请求，包括调用 id、工具名和参数。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """把 ToolCall 转成可写入文件或 API 响应的字典。"""
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolCall":
        """把字典里的字段校正并恢复成 ToolCall 对象。"""
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            arguments=dict(payload.get("arguments") or {}),
        )


@dataclass
class ToolResult:
    """承载工具执行后的观察结果，后续会回写给模型。"""

    tool_name: str
    content: str
    tool_call_id: str = ""
    is_error: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """根据 is_error 推导工具结果是否成功。"""
        return not self.is_error
