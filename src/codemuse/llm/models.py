"""定义模型层返回的统一结构：文本回复和工具调用列表。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codemuse.domain.tools import ToolCall


@dataclass
class LLMResponse:
    """统一表示模型一次回复：可以是文本，也可以是工具调用列表。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)
