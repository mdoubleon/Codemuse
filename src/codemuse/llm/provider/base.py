"""模块说明：CodeMuse 模型 Provider 基础协议模块。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolSpec
from codemuse.llm.models import LLMResponse


@dataclass(frozen=True)
class LLMProviderInfo:
    """LLMProviderInfo：描述一个模型 provider 的基础能力。"""
    provider: str
    model: str
    supports_tools: bool = True
    is_stub: bool = False


class LLMProvider(Protocol):
    """LLMProvider：定义 Runtime 可依赖的统一模型调用接口。"""

    @property
    def info(self) -> LLMProviderInfo:
        """返回 provider 的基础元信息。"""
        ...

    def complete(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> LLMResponse:
        """根据 messages 和 tools 生成模型回复或工具调用。"""
        ...
