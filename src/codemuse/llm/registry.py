"""根据模型配置创建 LLMProvider，并向 SDK/CLI 暴露 provider 清单。"""
from __future__ import annotations

import os
from dataclasses import dataclass

from codemuse.config.schema import ModelConfig
from codemuse.llm.fake import FakeLLM
from codemuse.llm.provider.bailian import BailianProvider
from codemuse.llm.provider.bailian import DEFAULT_BAILIAN_BASE_URL
from codemuse.llm.provider.base import LLMProvider
from codemuse.llm.provider.openai_compatible import OpenAICompatibleProvider
from codemuse.llm.provider.openai_compatible import DEFAULT_OPENAI_COMPATIBLE_BASE_URL


@dataclass(frozen=True)
class ProviderDescriptor:
    """记录一个模型 provider 的名称、描述和是否已实现。"""
    name: str
    description: str
    implemented: bool
    default_model: str
    default_base_url: str = ""
    default_api_key_env: str = ""


PROVIDERS: dict[str, ProviderDescriptor] = {
    "fake": ProviderDescriptor(
        name="fake",
        description="Deterministic local provider for tests and learning.",
        implemented=True,
        default_model="fake-local",
    ),
    "openai_compatible": ProviderDescriptor(
        name="openai_compatible",
        description="OpenAI-compatible chat completions provider.",
        implemented=True,
        default_model="gpt-4o-mini",
        default_base_url=DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
        default_api_key_env="OPENAI_API_KEY",
    ),
    "bailian": ProviderDescriptor(
        name="bailian",
        description="Alibaba Bailian / DashScope OpenAI-compatible provider.",
        implemented=True,
        default_model="qwen-plus",
        default_base_url=DEFAULT_BAILIAN_BASE_URL,
        default_api_key_env="DASHSCOPE_API_KEY",
    ),
}


def create_llm_provider(config: ModelConfig) -> LLMProvider:
    # 模型切换只发生在这里：Runtime 拿到的是统一的 LLMProvider，不关心具体厂商。
    """根据 ModelConfig 创建具体的 LLMProvider 实例。"""
    if config.provider == "fake":
        return FakeLLM(model=config.model)
    if config.provider == "openai_compatible":
        descriptor = PROVIDERS["openai_compatible"]
        return OpenAICompatibleProvider(
            model=config.model or descriptor.default_model,
            base_url=config.base_url or descriptor.default_base_url,
            api_key_env=config.api_key_env or descriptor.default_api_key_env,
        )
    if config.provider == "bailian":
        descriptor = PROVIDERS["bailian"]
        return BailianProvider(
            model=config.model or descriptor.default_model,
            base_url=config.base_url or descriptor.default_base_url,
            api_key_env=config.api_key_env or descriptor.default_api_key_env,
        )
    raise ValueError(f"Unknown LLM provider: {config.provider}")


def list_llm_providers() -> list[dict[str, object]]:
    # 这里暴露给 SDK/CLI 做能力查看，避免把 provider 清单做成大模型可调用工具。
    """返回模型 provider 清单，供 SDK 和 CLI 查询。"""
    return [
        {
            "name": descriptor.name,
            "description": descriptor.description,
            "implemented": descriptor.implemented,
            "default_model": descriptor.default_model,
            "default_base_url": descriptor.default_base_url,
            "default_api_key_env": descriptor.default_api_key_env,
            "api_key_present": bool(descriptor.default_api_key_env and os.environ.get(descriptor.default_api_key_env)),
        }
        for descriptor in PROVIDERS.values()
    ]


def provider_readiness(config: ModelConfig | None = None) -> list[dict[str, object]]:
    """Return readiness checks for every configured provider option."""
    configured = config or ModelConfig()
    items: list[dict[str, object]] = []
    for descriptor in PROVIDERS.values():
        model = configured.model if configured.provider == descriptor.name else descriptor.default_model
        base_url = configured.base_url if configured.provider == descriptor.name else descriptor.default_base_url
        api_key_env = configured.api_key_env if configured.provider == descriptor.name else descriptor.default_api_key_env
        if descriptor.name == "fake":
            ready = True
            reason = ""
        else:
            ready = bool(api_key_env and os.environ.get(api_key_env))
            reason = "" if ready else f"Environment variable {api_key_env} is not set."
        items.append(
            {
                "name": descriptor.name,
                "model": model,
                "implemented": descriptor.implemented,
                "ready": ready,
                "base_url": base_url,
                "api_key_env": api_key_env,
                "api_key_present": bool(api_key_env and os.environ.get(api_key_env)),
                "reason": reason,
            }
        )
    return items
