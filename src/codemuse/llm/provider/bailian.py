"""Alibaba Bailian / DashScope OpenAI-compatible provider."""
from __future__ import annotations

from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.llm.provider.openai_compatible import OpenAICompatibleProvider

DEFAULT_BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class BailianProvider(OpenAICompatibleProvider):
    """Use DashScope's OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "DASHSCOPE_API_KEY",
        base_url: str = DEFAULT_BAILIAN_BASE_URL,
        timeout_seconds: int = 60,
    ) -> None:
        """初始化 BailianProvider 并保存运行依赖。"""
        super().__init__(
            model=model,
            base_url=base_url,
            api_key_env=api_key_env or "DASHSCOPE_API_KEY",
            timeout_seconds=timeout_seconds,
        )
        self._info = LLMProviderInfo(provider="bailian", model=model, supports_tools=True, is_stub=False)

