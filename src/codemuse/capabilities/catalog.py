"""汇总工具、Skill 和 Extension 的能力目录并提供查询。"""
from __future__ import annotations

from codemuse.capabilities.descriptor import CapabilityDescriptor, CapabilityKind
from codemuse.capabilities.discovery import CapabilityDiscoveryProvider

CapabilityKey = tuple[str, str]


class CapabilityCatalog:
    """聚合多个能力发现来源，并提供去重后的能力快照。"""
    def __init__(self, providers: list[CapabilityDiscoveryProvider]) -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        self._providers = list(providers)
        self._snapshot: dict[CapabilityKey, CapabilityDescriptor] = {}
        self._ordered_keys: list[CapabilityKey] = []
        self.refresh()

    def list(self, kind: CapabilityKind | None = None) -> list[CapabilityDescriptor]:
        """列出全部能力，或只列出指定 kind 的能力。"""
        descriptors: list[CapabilityDescriptor] = []
        for key in self._ordered_keys:
            descriptor = self._snapshot[key]
            if kind is not None and descriptor.kind != kind:
                continue
            descriptors.append(descriptor)
        return descriptors

    def get(self, kind: CapabilityKind, name: str) -> CapabilityDescriptor:
        """按能力类型和名称读取单个能力描述。"""
        return self._snapshot[(kind, name)]

    def reload(self) -> None:
        """重新执行能力发现，刷新目录内的快照。"""
        for provider in self._providers:
            reload_fn = getattr(provider, "reload", None)
            if callable(reload_fn):
                reload_fn()
        self.refresh()

    def refresh(self) -> None:
        """为语义更清晰的调用者提供 reload 的别名。"""
        next_snapshot: dict[CapabilityKey, CapabilityDescriptor] = {}
        next_ordered_keys: list[CapabilityKey] = []
        for provider in self._providers:
            for descriptor in provider.discover():
                key = (descriptor.kind, descriptor.name)
                if key in next_snapshot:
                    raise ValueError(f"Duplicate capability discovered: {key!r}")
                next_snapshot[key] = descriptor
                next_ordered_keys.append(key)
        # Catalog 只保存描述信息，不保存工具实例执行状态。
        self._snapshot = next_snapshot
        self._ordered_keys = sorted(next_ordered_keys)
