"""管理工具注册、工具元数据、工具规格查询和工具执行。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from codemuse.tools.base import BaseTool, ToolResult, ToolSpec
from codemuse.tools.metadata import ToolMetadata

ToolFactory = Callable[[], BaseTool]


@dataclass
class ToolRegistration:
    """保存工具注册时的工厂、分类和权限元数据。"""
    name: str
    category: str
    tool_factory: ToolFactory
    metadata: ToolMetadata


class ToolRegistry:
    """统一管理工具的注册、查询、规格暴露和执行。"""
    def __init__(self, workspace: Path) -> None:
        """保存 workspace 路径，并准备工具注册表和实例缓存。"""
        self.workspace = workspace.resolve()
        self._registrations: dict[str, ToolRegistration] = {}
        self._instances: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool, *, category: str = "builtin") -> None:
        """把已创建的工具实例登记到注册表，并缓存实例。"""
        name = tool.spec.name
        if name in self._registrations:
            raise ValueError(f"Tool already registered: {name}")
        spec = tool.spec
        self._registrations[name] = ToolRegistration(
            name=name,
            category=category,
            tool_factory=lambda tool=tool: tool,
            metadata=ToolMetadata(
                name=name,
                category=category,
                permission_domain=spec.permission_domain,
                requires_confirmation=spec.requires_confirmation,
                model_callable=spec.model_callable,
                side_effect=spec.side_effect,
            ),
        )
        self._instances[name] = tool

    def register_factory(self, registration: ToolRegistration) -> None:
        """登记延迟创建工具的工厂，适合 MCP 等动态工具。"""
        if registration.name in self._registrations:
            raise ValueError(f"Tool already registered: {registration.name}")
        self._registrations[registration.name] = registration

    def names(self) -> list[str]:
        """返回已注册工具名称的排序列表。"""
        return sorted(self._registrations)

    def get(self, name: str) -> BaseTool:
        """按工具名读取工具实例；如果还没实例化，则通过 tool_factory 创建。"""
        if name not in self._registrations:
            raise ValueError(f"Unknown tool: {name}")
        if name not in self._instances:
            self._instances[name] = self._registrations[name].tool_factory()
        return self._instances[name]

    def get_spec(self, name: str) -> ToolSpec:
        """按工具名读取 ToolSpec，供 Runtime 查权限或给模型暴露。"""
        return self.get(name).spec

    def metadata(self) -> dict[str, ToolMetadata]:
        """返回工具注册时保存的权限和分类元数据。"""
        return {name: registration.metadata for name, registration in self._registrations.items()}

    def specs(self) -> list[ToolSpec]:
        """返回所有允许模型调用的 ToolSpec。"""
        specs: list[ToolSpec] = []
        for name in self.names():
            spec = self.get_spec(name)
            if spec.model_callable:
                specs.append(spec)
        return specs

    def spec_payloads(self) -> list[dict[str, Any]]:
        """把可调用工具规格转成字典，供模型层使用。"""
        return [spec.to_dict() for spec in self.specs()]

    def list_tools(self) -> list[dict[str, Any]]:
        """列出工具名、分类、权限域和副作用等调试信息。"""
        tools: list[dict[str, Any]] = []
        for name in self.names():
            spec = self.get_spec(name)
            metadata = self._registrations[name].metadata
            tools.append(
                {
                    "name": name,
                    "category": metadata.category,
                    "description": spec.description,
                    "permission_domain": spec.permission_domain,
                    "requires_confirmation": spec.requires_confirmation,
                    "model_callable": spec.model_callable,
                    "side_effect": spec.side_effect,
                }
            )
        return tools

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """执行已通过注册表和策略检查的工具动作。"""
        tool = self.get(name)
        if not tool.spec.model_callable:
            raise PermissionError(f"Tool is not model-callable: {name}")
        # 是否需要审批由 AgentRuntime 统一判断；registry 只负责找到工具并执行。
        return tool.execute(arguments)
