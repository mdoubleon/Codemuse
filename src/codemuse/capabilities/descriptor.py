"""实现 capabilities/descriptor.py 对应的业务边界和辅助逻辑。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

CapabilityKind = Literal[
    "builtin_tool",
    "mcp_tool",
    "subagent_tool",
    "memory_tool",
    "repo_tool",
    "web_tool",
    "skill",
    "extension",
]


@dataclass(frozen=True)
class CapabilityDescriptor:
    """CapabilityDescriptor：描述一个能力或外部对象的元数据。"""
    kind: CapabilityKind
    name: str
    description: str
    source: str
    status: str = "loaded"
    risk_level: str = "low"
    cost_hint: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """在 dataclass 初始化后执行字段校验或派生处理。"""
        try:
            json.dumps(self.metadata, ensure_ascii=False)
        except TypeError as exc:
            raise TypeError("Capability metadata must be JSON-serializable.") from exc

    def to_dict(self) -> dict[str, Any]:
        """把 CapabilityDescriptor 转成可写入文件或 API 响应的字典。"""
        return {
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "status": self.status,
            "risk_level": self.risk_level,
            "cost_hint": self.cost_hint,
            "metadata": dict(self.metadata),
        }
