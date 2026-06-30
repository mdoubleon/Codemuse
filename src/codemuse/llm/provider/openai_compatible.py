"""OpenAI-compatible chat completions provider."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolCall, ToolSpec
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo

DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class ProviderReadiness:
    """Readiness metadata for a live model provider."""

    provider: str
    model: str
    implemented: bool
    ready: bool
    api_key_env: str
    api_key_present: bool
    base_url: str
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        """将 ProviderReadiness 转换为可序列化字典。"""
        return {
            "provider": self.provider,
            "model": self.model,
            "implemented": self.implemented,
            "ready": self.ready,
            "api_key_env": self.api_key_env,
            "api_key_present": self.api_key_present,
            "base_url": self.base_url,
            "reason": self.reason,
        }


class OpenAICompatibleProvider:
    """Call an OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "",
        api_key_env: str = "OPENAI_API_KEY",
        timeout_seconds: int = 60,
    ) -> None:
        """初始化 OpenAICompatibleProvider 并保存运行依赖。"""
        self.model = model
        self.base_url = _normalize_base_url(base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL)
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.timeout_seconds = timeout_seconds
        self._info = LLMProviderInfo(provider="openai_compatible", model=model, supports_tools=True, is_stub=False)

    @property
    def info(self) -> LLMProviderInfo:
        """Return provider metadata."""
        return self._info

    def readiness(self) -> ProviderReadiness:
        """处理 就绪状态。"""
        api_key_present = bool(os.environ.get(self.api_key_env))
        return ProviderReadiness(
            provider=self.info.provider,
            model=self.model,
            implemented=True,
            ready=api_key_present,
            api_key_env=self.api_key_env,
            api_key_present=api_key_present,
            base_url=self.base_url,
            reason="" if api_key_present else f"Environment variable {self.api_key_env} is not set.",
        )

    def complete(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> LLMResponse:
        """Call the configured chat completions endpoint."""
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key environment variable: {self.api_key_env}")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_payload(message) for message in messages],
        }
        tool_payload = [_tool_to_payload(tool) for tool in tools if tool.model_callable]
        if tool_payload:
            payload["tools"] = tool_payload
            payload["tool_choice"] = "auto"
        response = self._post_chat_completions(payload, api_key=api_key)
        return _response_from_payload(response, provider=self.info.provider, model=self.model)

    def _post_chat_completions(self, payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
        """处理 postchatcompletions。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Provider request failed: {exc.reason}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            preview = raw.strip().replace("\n", " ")[:240] or "<empty response>"
            raise RuntimeError(f"Provider response was not valid JSON from {url}: {preview}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Provider response was not a JSON object.")
        return data


def _normalize_base_url(value: str) -> str:
    """处理 normalize基础URL。"""
    return value.rstrip("/")


def _message_to_payload(message: ChatMessage) -> dict[str, Any]:
    """处理 消息to载荷。"""
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.text_content(),
        }
    payload: dict[str, Any] = {"role": message.role, "content": message.text_content()}
    if message.role == "assistant" and message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _tool_to_payload(tool: ToolSpec) -> dict[str, Any]:
    """处理 工具to载荷。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


def _response_from_payload(payload: dict[str, Any], *, provider: str, model: str) -> LLMResponse:
    """处理 响应from载荷。"""
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("Provider response did not include choices.")
    message = dict(choices[0].get("message") or {})
    text = str(message.get("content") or "")
    tool_calls: list[ToolCall] = []
    for raw_call in message.get("tool_calls") or []:
        function = raw_call.get("function") or {}
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Tool call arguments were not valid JSON: {raw_arguments}") from exc
        tool_calls.append(
            ToolCall(
                id=str(raw_call.get("id") or uuid.uuid4()),
                name=str(function.get("name") or ""),
                arguments=arguments,
            )
        )
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        usage={key: int(value) for key, value in usage.items() if isinstance(value, int)},
        provider_metadata={
            "provider": provider,
            "model": model,
            "response_id": payload.get("id") or "",
            "finish_reason": choices[0].get("finish_reason") or "",
        },
    )
