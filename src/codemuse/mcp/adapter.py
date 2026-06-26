"""把 MCP 工具描述适配成 CodeMuse BaseTool，让 Runtime 按普通工具调用。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from codemuse.domain.tools import ToolSpec
from codemuse.mcp.descriptors import MCPToolDescriptor
from codemuse.mcp.manager import MCPManager
from codemuse.tools.base import BaseTool, ToolResult
from codemuse.tools.metadata import ToolMetadata
from codemuse.tools.registry import ToolRegistration, ToolRegistry


class MCPToolAdapter(BaseTool):
    """把 MCP 工具适配成 CodeMuse 普通工具。

    这是关键边界：MCP 是外部协议，Runtime 不直接认识它；
    Adapter 负责把它转换成 ToolSpec / ToolResult。
    """

    def __init__(
        self,
        workspace: Path,
        *,
        manager: MCPManager,
        descriptor: MCPToolDescriptor,
        public_name: str,
    ) -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        super().__init__(workspace)
        self.manager = manager
        self.descriptor = descriptor
        self.public_name = public_name

    @property
    def spec(self) -> ToolSpec:
        """声明该工具暴露给模型和注册表的调用规格。"""
        return ToolSpec(
            name=self.public_name,
            description=f"MCP tool `{self.descriptor.name}` from server `{self.descriptor.server_name}`. {self.descriptor.description}".strip(),
            parameters=self.descriptor.input_schema,
            requires_confirmation=self.descriptor.approval_mode == "ask" or self.descriptor.is_destructive,
            permission_domain=self._permission_domain(),
            side_effect=self.descriptor.is_destructive,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """执行已通过注册表和策略检查的工具动作。"""
        result = self.manager.call_mcp_tool(self.descriptor.server_name, self.descriptor.name, arguments)
        content = result.content or json.dumps(result.payload, ensure_ascii=False)
        return ToolResult(
            tool_name=self.public_name,
            content=content,
            is_error=result.is_error,
            details={
                "mcp_server": result.server_name,
                "mcp_tool": result.name_or_uri,
                "mcp_metadata": result.metadata,
                "payload": result.payload,
            },
        )

    def _permission_domain(self) -> str:
        """为该流程的公共逻辑提供局部辅助处理。"""
        if self.descriptor.is_destructive:
            return "write"
        if self.descriptor.is_remote:
            return "network"
        if self.descriptor.requires_auth:
            return "external"
        return "read"


class MCPStatusTool(BaseTool):
    """Expose MCP lifecycle and discovery state for diagnostics and UI."""

    def __init__(self, workspace: Path, manager: MCPManager) -> None:
        super().__init__(workspace)
        self.manager = manager

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mcp_status",
            description="Report configured MCP servers, transport state, auth requirements, discovered tools, and errors.",
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
            permission_domain="read",
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        report = self.manager.status_report()
        lines = [
            "# MCP Status",
            "",
            f"- servers: {report['server_count']}",
            f"- ready: {report['ready_count']}",
        ]
        for server in report["servers"]:
            lines.append("")
            lines.append(f"## {server['name']}")
            lines.append(f"- transport: {server['transport']}")
            lines.append(f"- status: {server['status']}")
            lines.append(f"- tools: {server['tool_count']}")
            if server.get("error"):
                lines.append(f"- error: {server['error']}")
        return ToolResult(tool_name=self.spec.name, content="\n".join(lines), details={"mcp": report})


def register_mcp_tools(registry: ToolRegistry, workspace: Path, manager: MCPManager) -> list[str]:
    """发现 MCP 工具，并注册到 ToolRegistry。

    返回注册的工具名，方便测试和启动日志以后展示。
    """

    registered: list[str] = []
    registry.register(MCPStatusTool(workspace, manager), category="mcp")
    registered.append("mcp_status")
    for descriptor in manager.discover_tools():
        public_name = public_mcp_tool_name(manager.tool_prefix, descriptor.server_name, descriptor.name)
        registration = ToolRegistration(
            name=public_name,
            category="mcp",
            tool_factory=lambda descriptor=descriptor, public_name=public_name: MCPToolAdapter(
                workspace,
                manager=manager,
                descriptor=descriptor,
                public_name=public_name,
            ),
            metadata=ToolMetadata(
                name=public_name,
                category="mcp",
                permission_domain="write" if descriptor.is_destructive else ("network" if descriptor.is_remote else "read"),
                requires_confirmation=descriptor.approval_mode == "ask" or descriptor.is_destructive,
                model_callable=True,
                side_effect=descriptor.is_destructive,
            ),
        )
        registry.register_factory(registration)
        registered.append(public_name)
    return registered


def public_mcp_tool_name(prefix: str, server_name: str, tool_name: str) -> str:
    """把 MCP server 名和原始工具名组合成模型可调用的公共工具名。"""
    return "__".join([_safe_name(prefix), _safe_name(server_name), _safe_name(tool_name)])


def _safe_name(value: str) -> str:
    """生成安全可控的内部表示，避免路径或名称越界。"""
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "tool"
