"""实现 capabilities/discovery.py 对应的业务边界和辅助逻辑。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codemuse.capabilities.descriptor import CapabilityDescriptor, CapabilityKind
from codemuse.tools.registry import ToolRegistry


class CapabilityDiscoveryProvider(Protocol):
    """能力发现 provider 协议，返回当前来源可暴露的能力列表。"""
    def discover(self) -> list[CapabilityDescriptor]:
        """发现并返回能力描述。"""
        ...


@dataclass
class ToolCapabilityDiscoveryProvider:
    """从 ToolRegistry 中生成工具能力描述。"""
    registry: ToolRegistry

    def discover(self) -> list[CapabilityDescriptor]:
        """把已注册工具转换为 UI/CLI 可展示的 CapabilityDescriptor。"""
        descriptors: list[CapabilityDescriptor] = []
        metadata_map = self.registry.metadata()
        for name in self.registry.names():
            spec = self.registry.get_spec(name)
            metadata = metadata_map[name]
            descriptors.append(
                CapabilityDescriptor(
                    kind=_kind_for_category(metadata.category),
                    name=name,
                    description=spec.description,
                    source=f"{metadata.category}:{name}",
                    risk_level=_risk_level(spec.permission_domain, spec.requires_confirmation, spec.side_effect),
                    cost_hint=_cost_hint(metadata.category),
                    metadata={
                        "category": metadata.category,
                        "permission_domain": spec.permission_domain,
                        "requires_confirmation": spec.requires_confirmation,
                        "model_callable": spec.model_callable,
                        "side_effect": spec.side_effect,
                    },
                )
            )
        return descriptors


def _kind_for_category(category: str) -> CapabilityKind:
    """把工具元数据分类映射为能力类型。"""
    if category == "mcp":
        return "mcp_tool"
    if category == "subagent":
        return "subagent_tool"
    if category == "memory":
        return "memory_tool"
    if category == "repo":
        return "repo_tool"
    if category == "web":
        return "web_tool"
    if category == "skill":
        return "skill"
    if category == "extension":
        return "extension"
    return "builtin_tool"


def _risk_level(permission_domain: str, requires_confirmation: bool, side_effect: bool) -> str:
    """根据权限域和副作用估算展示给用户的风险等级。"""
    if requires_confirmation or side_effect:
        return "medium"
    if permission_domain in {"shell", "network", "external", "write"}:
        return "medium"
    return "low"


def _cost_hint(category: str) -> str:
    """根据能力类别给出粗略成本提示。"""
    if category in {"mcp", "subagent", "repo", "web"}:
        return "medium"
    return "low"
