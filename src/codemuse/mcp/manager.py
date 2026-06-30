"""统一管理 MCP 配置、工具发现、工具调用和会话关闭。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from codemuse.mcp.config import MCPServerConfig, load_mcp_config
from codemuse.mcp.descriptors import MCPToolDescriptor
from codemuse.mcp.results import MCPResult
from codemuse.mcp.session import MCPSessionManager


class MCPManager:
    """MCP 配置、发现和调用的统一入口。

    bootstrap 只需要创建 manager；工具适配器只需要找 manager 调用外部工具。
    """

    def __init__(self, servers: list[MCPServerConfig], *, tool_prefix: str = "mcp") -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self._servers = {server.name: server for server in servers}
        self.tool_prefix = tool_prefix
        self._sessions = MCPSessionManager()

    @classmethod
    def from_workspace(cls, workspace: Path, *, config_paths: list[Path] | None = None) -> "MCPManager":
        """从 workspace 的 MCP 配置创建管理器实例。"""
        document = load_mcp_config(workspace.resolve(), config_paths=config_paths)
        return cls(document.servers, tool_prefix=document.settings.tool_prefix)

    def server_names(self) -> list[str]:
        """列出已加载的 MCP server 名称。"""
        return sorted(self._servers)

    def server_config(self, server_name: str) -> MCPServerConfig:
        """按 server 名称读取对应 MCP server 配置。"""
        return self._servers[server_name]

    def list_mcp_tools(self, server_name: str) -> list[MCPToolDescriptor]:
        """发现并返回指定 MCP server 暴露的工具描述。"""
        server = self.server_config(server_name)
        session = self._sessions.get_or_create(server)
        descriptors: list[MCPToolDescriptor] = []
        for item in session.list_tools():
            descriptors.append(
                MCPToolDescriptor(
                    server_name=server.name,
                    name=str(item["name"]),
                    description=str(item.get("description") or ""),
                    input_schema=dict(item.get("input_schema") or item.get("inputSchema") or {}),
                    is_remote=server.is_remote,
                    requires_auth=server.requires_auth,
                    is_destructive=bool(item.get("is_destructive")),
                    approval_mode=str(item.get("approval_mode") or server.approval_mode),
                    metadata={"transport": server.transport},
                )
            )
        return descriptors

    def discover_tools(self) -> list[MCPToolDescriptor]:
        """遍历所有 MCP server，收集它们暴露的工具描述。"""
        tools: list[MCPToolDescriptor] = []
        for server_name in self.server_names():
            try:
                tools.extend(self.list_mcp_tools(server_name))
            except NotImplementedError:
                # Stage 8 只支持 mock transport；真实 stdio/http 后续再接入。
                continue
        return tools

    def status_report(self) -> dict[str, Any]:
        """Return server lifecycle, discovery, auth, and transport status for diagnostics."""
        servers: list[dict[str, Any]] = []
        for server_name in self.server_names():
            server = self.server_config(server_name)
            item: dict[str, Any] = {
                "name": server.name,
                "transport": server.transport,
                "is_remote": server.is_remote,
                "requires_auth": server.requires_auth,
                "approval_mode": server.approval_mode,
                "status": "unknown",
                "tool_count": 0,
                "error": "",
            }
            try:
                tools = self.list_mcp_tools(server_name)
                item["status"] = "ready"
                item["tool_count"] = len(tools)
                item["tools"] = [tool.name for tool in tools]
            except Exception as exc:  # noqa: BLE001 - diagnostic surface should report failures
                item["status"] = "error"
                item["error"] = f"{type(exc).__name__}: {exc}"
            servers.append(item)
        return {
            "tool_prefix": self.tool_prefix,
            "server_count": len(servers),
            "ready_count": sum(1 for item in servers if item["status"] == "ready"),
            "servers": servers,
        }

    def call_mcp_tool(self, server_name: str, name: str, arguments: dict[str, Any]) -> MCPResult:
        """找到目标 MCP session，调用指定外部工具并包装成 MCPResult。"""
        server = self.server_config(server_name)
        session = self._sessions.get_or_create(server)
        payload = session.client.call_tool(name, arguments)
        session.touch(time.time())
        return MCPResult(
            server_name=server_name,
            kind="mcp_tool",
            name_or_uri=name,
            content=str(payload.get("content") or ""),
            payload=dict(payload.get("payload") or {}),
            is_error=bool(payload.get("is_error")),
            metadata={"source_server": server_name, "transport": server.transport},
        )

    def close_all_sessions(self) -> list[str]:
        """关闭管理器中缓存的所有 MCP session。"""
        return self._sessions.close_all_sessions()
