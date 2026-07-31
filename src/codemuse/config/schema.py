"""定义 CodeMuse 配置结构和校验规则，包括模型、Runtime 和能力开关。"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
import re
from typing import Any


_ENVIRONMENT_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_DEFAULT_MODEL_BY_PROVIDER = {
    "fake": "fake-local",
    "openai_compatible": "gpt-4o-mini",
    "bailian": "qwen-plus",
    "deepseek": "deepseek-chat",
}


@dataclass(frozen=True)
class ModelConfig:
    """ModelConfig：保存该能力运行需要的配置字段。"""
    provider: str = "fake"
    model: str = "fake-local"
    base_url: str = ""
    api_key_env: str = ""
    temperature: float | None = None
    max_tokens: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelConfig":
        """把字典里的字段校正并恢复成 ModelConfig 对象。"""
        provider = _string_value(payload.get("provider", "fake"), "model.provider")
        if provider not in {"fake", "openai_compatible", "bailian", "deepseek"}:
            raise ConfigValidationError(f"model.provider is not supported: {provider}")
        model = _string_value(
            payload.get("model", _DEFAULT_MODEL_BY_PROVIDER[provider]),
            "model.model",
        )
        if not model:
            raise ConfigValidationError("model.model cannot be empty.")
        base_url = _string_value(payload.get("base_url", ""), "model.base_url")
        api_key_env = _string_value(payload.get("api_key_env", ""), "model.api_key_env")
        if api_key_env and not _ENVIRONMENT_VARIABLE_NAME.fullmatch(api_key_env):
            raise ConfigValidationError(
                "model.api_key_env must be an environment variable name; do not provide a raw API key."
            )
        temperature = _optional_temperature_value(payload.get("temperature"), "model.temperature")
        max_tokens = _optional_positive_int_value(payload.get("max_tokens"), "model.max_tokens")
        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        """把 ModelConfig 转成可写入文件或 API 响应的字典。"""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


@dataclass(frozen=True)
class RuntimeConfig:
    """RuntimeConfig：保存该能力运行需要的配置字段。"""
    max_turns: int = 8
    max_tool_calls_per_turn: int = 4
    max_tool_calls_per_prompt: int = 8
    history_token_budget: int = 16000
    tools_enabled: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeConfig":
        """把字典里的字段校正并恢复成 RuntimeConfig 对象。"""
        max_turns = int(payload.get("max_turns", 8))
        if max_turns < 1 or max_turns > 50:
            raise ConfigValidationError("runtime.max_turns must be between 1 and 50.")
        max_tool_calls_per_turn = int(payload.get("max_tool_calls_per_turn", 4))
        if max_tool_calls_per_turn < 1 or max_tool_calls_per_turn > 32:
            raise ConfigValidationError("runtime.max_tool_calls_per_turn must be between 1 and 32.")
        max_tool_calls_per_prompt = int(payload.get("max_tool_calls_per_prompt", 8))
        if max_tool_calls_per_prompt < 1 or max_tool_calls_per_prompt > 64:
            raise ConfigValidationError("runtime.max_tool_calls_per_prompt must be between 1 and 64.")
        history_token_budget = int(payload.get("history_token_budget", 16000))
        if history_token_budget < 256 or history_token_budget > 128000:
            raise ConfigValidationError("runtime.history_token_budget must be between 256 and 128000.")
        tools_enabled = _bool_value(payload.get("tools_enabled", True), "runtime.tools_enabled")
        return cls(
            max_turns=max_turns,
            max_tool_calls_per_turn=max_tool_calls_per_turn,
            max_tool_calls_per_prompt=max_tool_calls_per_prompt,
            history_token_budget=history_token_budget,
            tools_enabled=tools_enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        """把 RuntimeConfig 转成可写入文件或 API 响应的字典。"""
        return {
            "max_turns": self.max_turns,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "max_tool_calls_per_prompt": self.max_tool_calls_per_prompt,
            "history_token_budget": self.history_token_budget,
            "tools_enabled": self.tools_enabled,
        }


@dataclass(frozen=True)
class CapabilitiesConfig:
    """CapabilitiesConfig：保存该能力运行需要的配置字段。"""
    mcp_enabled: bool = True
    subagents_enabled: bool = True
    memory_enabled: bool = True
    web_enabled: bool = True
    skills_enabled: bool = True
    extensions_enabled: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CapabilitiesConfig":
        """把字典里的字段校正并恢复成 CapabilitiesConfig 对象。"""
        return cls(
            mcp_enabled=_bool_value(payload.get("mcp_enabled", True), "capabilities.mcp_enabled"),
            subagents_enabled=_bool_value(payload.get("subagents_enabled", True), "capabilities.subagents_enabled"),
            memory_enabled=_bool_value(payload.get("memory_enabled", True), "capabilities.memory_enabled"),
            web_enabled=_bool_value(payload.get("web_enabled", True), "capabilities.web_enabled"),
            skills_enabled=_bool_value(payload.get("skills_enabled", True), "capabilities.skills_enabled"),
            extensions_enabled=_bool_value(payload.get("extensions_enabled", True), "capabilities.extensions_enabled"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把 CapabilitiesConfig 转成可写入文件或 API 响应的字典。"""
        return {
            "mcp_enabled": self.mcp_enabled,
            "subagents_enabled": self.subagents_enabled,
            "memory_enabled": self.memory_enabled,
            "web_enabled": self.web_enabled,
            "skills_enabled": self.skills_enabled,
            "extensions_enabled": self.extensions_enabled,
        }


@dataclass(frozen=True)
class CodeMuseConfig:
    """CodeMuseConfig：保存该能力运行需要的配置字段。"""
    model: ModelConfig = field(default_factory=ModelConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CodeMuseConfig":
        """把字典里的字段校正并恢复成 CodeMuseConfig 对象。"""
        data = dict(payload or {})
        _reject_unknown_keys(data, {"model", "runtime", "capabilities"}, "")
        model_payload = _object_value(data.get("model", {}), "model")
        runtime_payload = _object_value(data.get("runtime", {}), "runtime")
        capabilities_payload = _object_value(data.get("capabilities", {}), "capabilities")
        _reject_unknown_keys(
            model_payload,
            {"provider", "model", "base_url", "api_key_env", "temperature", "max_tokens"},
            "model",
        )
        _reject_unknown_keys(
            runtime_payload,
            {
                "max_turns",
                "max_tool_calls_per_turn",
                "max_tool_calls_per_prompt",
                "history_token_budget",
                "tools_enabled",
            },
            "runtime",
        )
        _reject_unknown_keys(
            capabilities_payload,
            {
                "mcp_enabled",
                "subagents_enabled",
                "memory_enabled",
                "web_enabled",
                "skills_enabled",
                "extensions_enabled",
            },
            "capabilities",
        )
        return cls(
            model=ModelConfig.from_dict(model_payload),
            runtime=RuntimeConfig.from_dict(runtime_payload),
            capabilities=CapabilitiesConfig.from_dict(capabilities_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        """把 CodeMuseConfig 转成可写入文件或 API 响应的字典。"""
        return {
            "model": self.model.to_dict(),
            "runtime": self.runtime.to_dict(),
            "capabilities": self.capabilities.to_dict(),
        }


class ConfigValidationError(ValueError):
    """表示项目配置解析或校验失败。"""
    pass


def default_config() -> CodeMuseConfig:
    """创建一份默认 CodeMuseConfig，作为配置合并的基底。"""
    return CodeMuseConfig()


def config_schema() -> dict[str, Any]:
    """返回配置字段的类型、默认值和说明。"""
    return {
        "fields": [
            {
                "path": "model.provider",
                "type": "string",
                "default": "fake",
                "description": "LLM provider name. Workspace config cannot override connection settings.",
                "workspace_writable": False,
            },
            {
                "path": "model.model",
                "type": "string",
                "default": "fake-local",
                "description": "Model identifier passed to the provider.",
            },
            {
                "path": "model.base_url",
                "type": "string",
                "default": "",
                "description": "Base URL for OpenAI-compatible providers; user, environment, or runtime only.",
                "workspace_writable": False,
            },
            {
                "path": "model.api_key_env",
                "type": "string",
                "default": "",
                "description": "Environment variable name for live providers; user, environment, or runtime only.",
                "workspace_writable": False,
            },
            {
                "path": "model.temperature",
                "type": "number",
                "default": None,
                "nullable": True,
                "minimum": 0,
                "maximum": 2,
                "description": "Optional sampling temperature for OpenAI-compatible live providers.",
            },
            {
                "path": "model.max_tokens",
                "type": "integer",
                "default": None,
                "nullable": True,
                "minimum": 1,
                "description": "Optional completion-token limit for OpenAI-compatible live providers.",
            },
            {
                "path": "runtime.max_turns",
                "type": "integer",
                "default": 8,
                "minimum": 1,
                "maximum": 50,
                "description": "Maximum tool-driven turns per prompt before a forced final answer.",
            },
            {
                "path": "runtime.max_tool_calls_per_turn",
                "type": "integer",
                "default": 4,
                "minimum": 1,
                "maximum": 32,
                "description": "Maximum distinct tool calls executed from one model response.",
            },
            {
                "path": "runtime.max_tool_calls_per_prompt",
                "type": "integer",
                "default": 8,
                "minimum": 1,
                "maximum": 64,
                "description": "Maximum accepted tool calls across one user prompt before a forced final answer.",
            },
            {
                "path": "runtime.history_token_budget",
                "type": "integer",
                "default": 16000,
                "minimum": 256,
                "maximum": 128000,
                "description": "Approximate token budget for persisted conversation history sent to the model.",
            },
            {
                "path": "runtime.tools_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether this chat may expose and execute tools.",
            },
            {
                "path": "capabilities.mcp_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether bootstrap registers MCP tools.",
            },
            {
                "path": "capabilities.subagents_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether bootstrap registers subagent tools.",
            },
            {
                "path": "capabilities.memory_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether bootstrap registers memory tools and recall.",
            },
            {
                "path": "capabilities.web_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether bootstrap registers guarded web tools.",
            },
            {
                "path": "capabilities.skills_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether bootstrap discovers workspace skill descriptors.",
            },
            {
                "path": "capabilities.extensions_enabled",
                "type": "boolean",
                "default": True,
                "description": "Whether bootstrap discovers workspace extension manifests.",
            },
        ]
    }


def _object_value(value: Any, path: str) -> dict[str, Any]:
    """校验配置片段是对象类型，并返回可修改的字典副本。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{path} must be an object.")
    return dict(value)


def _bool_value(value: Any, path: str) -> bool:
    """把配置值解析成布尔值，空值时使用默认值。"""
    if isinstance(value, bool):
        return value
    raise ConfigValidationError(f"{path} must be a boolean.")


def _string_value(value: Any, path: str) -> str:
    """把可选配置值解析成去除首尾空白的字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    raise ConfigValidationError(f"{path} must be a string.")


def _optional_temperature_value(value: Any, path: str) -> float | None:
    """Validate an optional OpenAI-compatible sampling temperature."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigValidationError(f"{path} must be a number or null.")
    result = float(value)
    if not isfinite(result) or result < 0 or result > 2:
        raise ConfigValidationError(f"{path} must be between 0 and 2.")
    return result


def _optional_positive_int_value(value: Any, path: str) -> int | None:
    """Validate an optional positive integer model limit."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigValidationError(f"{path} must be an integer or null.")
    if value < 1:
        raise ConfigValidationError(f"{path} must be greater than zero.")
    return value


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], prefix: str) -> None:
    """拒绝 schema 未声明的配置字段，避免拼写错误被静默忽略。"""
    unknown = sorted(set(data) - allowed)
    if not unknown:
        return
    path = f"{prefix}." if prefix else ""
    # 配置层提前拒绝拼错的字段，避免用户以为配置生效了但实际没有。
    raise ConfigValidationError(f"Unknown config field: {path}{unknown[0]}")
