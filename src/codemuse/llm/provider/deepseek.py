"""DeepSeek chat completions provider."""
from __future__ import annotations

from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.llm.provider.openai_compatible import OpenAICompatibleProvider

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_DEEPSEEK_TEMPERATURE = 0.2


class DeepSeekProvider(OpenAICompatibleProvider):
    """Use DeepSeek's OpenAI-compatible chat completions API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        api_key_env: str = DEFAULT_DEEPSEEK_API_KEY_ENV,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        temperature: float | None = DEFAULT_DEEPSEEK_TEMPERATURE,
        max_tokens: int | None = None,
        timeout_seconds: int = 60,
        max_retries: int = 2,
    ) -> None:
        selected_model = model.strip() or DEFAULT_DEEPSEEK_MODEL
        super().__init__(
            model=selected_model,
            base_url=base_url or DEFAULT_DEEPSEEK_BASE_URL,
            api_key_env=api_key_env or DEFAULT_DEEPSEEK_API_KEY_ENV,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self._info = LLMProviderInfo(provider="deepseek", model=selected_model, supports_tools=True, is_stub=False)
