"""管理可用子 Agent 规格，提供注册、查询和列出。"""
from __future__ import annotations

from codemuse.subagents.specs import SubAgentSpec, default_subagent_specs


class SubAgentCatalog:
    """子 Agent 规格目录。

    Catalog 负责“有哪些子 Agent”，Manager 负责“怎么运行子 Agent”。
    """

    def __init__(self, specs: dict[str, SubAgentSpec] | None = None) -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        self._specs: dict[str, SubAgentSpec] = {}
        for spec in (specs or default_subagent_specs()).values():
            self.register(spec)

    def register(self, spec: SubAgentSpec, *, replace: bool = False) -> None:
        """把已创建的工具实例登记到注册表，并缓存实例。"""
        if spec.name in self._specs and not replace:
            raise ValueError(f"Subagent already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> SubAgentSpec:
        """按名称读取子 Agent 规格。"""
        if name not in self._specs:
            raise ValueError(f"Unknown subagent: {name}")
        return self._specs[name]

    def list(self) -> list[SubAgentSpec]:
        """列出当前存储或目录中的对象。"""
        return [self._specs[name] for name in sorted(self._specs)]

    def names(self) -> list[str]:
        """返回已注册工具名称的排序列表。"""
        return sorted(self._specs)
