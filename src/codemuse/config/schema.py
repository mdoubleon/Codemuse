"""定义 CodeMuse 配置结构和校验规则，包括模型、Runtime 和能力开关。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    """ModelConfig：保存该能力运行需要的配置字段。"""
    provider: str = "fake"
    model: str = "fake-local"
    base_url: str = ""
    api_key_env: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelConfig":
        """把字典里的字段校正并恢复成 ModelConfig 对象。"""
        provider = _string_value(payload.get("provider", "fake"), "model.provider")
        if provider not in {"fake", "openai_compatible", "bailian"}:
            raise ConfigValidationError(f"model.provider is not supported: {provider}")
        model = _string_value(payload.get("model", "fake-local"), "model.model")
        if not model:
            raise ConfigValidationError("model.model cannot be empty.")
        base_url = _string_value(payload.get("base_url", ""), "model.base_url")
        api_key_env = _string_value(payload.get("api_key_env", ""), "model.api_key_env")
        return cls(provider=provider, model=model, base_url=base_url, api_key_env=api_key_env)

    def to_dict(self) -> dict[str, Any]:
        """把 ModelConfig 转成可写入文件或 API 响应的字典。"""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
        }


@dataclass(frozen=True)
class RuntimeConfig:
    """RuntimeConfig：保存该能力运行需要的配置字段。"""
    max_turns: int = 8

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeConfig":
        """把字典里的字段校正并恢复成 RuntimeConfig 对象。"""
        max_turns = int(payload.get("max_turns", 8))
        if max_turns < 1 or max_turns > 50:
            raise ConfigValidationError("runtime.max_turns must be between 1 and 50.")
        return cls(max_turns=max_turns)

    def to_dict(self) -> dict[str, Any]:
        """把 RuntimeConfig 转成可写入文件或 API 响应的字典。"""
        return {"max_turns": self.max_turns}


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
        _reject_unknown_keys(model_payload, {"provider", "model", "base_url", "api_key_env"}, "model")
        _reject_unknown_keys(runtime_payload, {"max_turns"}, "runtime")
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
                "description": "LLM provider name.",
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
                "description": "Base URL for OpenAI-compatible providers.",
            },
            {
                "path": "model.api_key_env",
                "type": "string",
                "default": "",
                "description": "Environment variable name for live providers.",
            },
            {
                "path": "runtime.max_turns",
                "type": "integer",
                "default": 8,
                "minimum": 1,
                "maximum": 50,
                "description": "Maximum ReAct loop turns per prompt.",
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


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], prefix: str) -> None:
    """拒绝 schema 未声明的配置字段，避免拼写错误被静默忽略。"""
    unknown = sorted(set(data) - allowed)
    if not unknown:
        return
    path = f"{prefix}." if prefix else ""
    # 配置层提前拒绝拼错的字段，避免用户以为配置生效了但实际没有。
    raise ConfigValidationError(f"Unknown config field: {path}{unknown[0]}")
