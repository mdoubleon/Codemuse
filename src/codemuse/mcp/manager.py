"""统一管理 MCP 配置、工具发现、工具调用和会话关闭。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from codemuse.mcp.config import MCPServerConfig, MCPTransportSettings, load_mcp_config
from codemuse.mcp.descriptors import MCPPromptDescriptor, MCPResourceDescriptor, MCPToolDescriptor
from codemuse.mcp.results import MCPResult
from codemuse.mcp.session import MCPSessionManager


class MCPManager:
    """MCP 配置、发现和调用的统一入口。

    bootstrap 只需要创建 manager；工具适配器只需要找 manager 调用外部工具。
    """

    def __init__(
        self,
        servers: list[MCPServerConfig],
        *,
        tool_prefix: str = "mcp",
        settings: MCPTransportSettings | None = None,
        workspace: Path | None = None,
        config_paths: list[Path] | None = None,
    ) -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self._servers = _server_map(servers)
        self.settings = settings or MCPTransportSettings(tool_prefix=tool_prefix)
        self.tool_prefix = self.settings.tool_prefix or tool_prefix
        self._workspace = workspace.resolve() if workspace is not None else None
        self._config_paths = list(config_paths) if config_paths is not None else None
        self._sessions = MCPSessionManager()
        self._descriptors: dict[str, list[MCPToolDescriptor]] = {}
        self._active: set[str] = set()
        self._errors: dict[str, str] = {}

    @classmethod
    def from_workspace(cls, workspace: Path, *, config_paths: list[Path] | None = None) -> "MCPManager":
        """从 workspace 的 MCP 配置创建管理器实例。"""
        resolved_workspace = workspace.resolve()
        document = load_mcp_config(resolved_workspace, config_paths=config_paths)
        return cls(
            document.servers,
            tool_prefix=document.settings.tool_prefix,
            settings=document.settings,
            workspace=resolved_workspace,
            config_paths=config_paths,
        )

    def server_names(self) -> list[str]:
        """列出已加载的 MCP server 名称。"""
        return sorted(self._servers)

    def server_config(self, server_name: str) -> MCPServerConfig:
        """按 server 名称读取对应 MCP server 配置。"""
        return self._servers[server_name]

    def is_active(self, server_name: str) -> bool:
        """Return whether a live MCP session has been explicitly activated."""
        return server_name in self._active

    def active_server_names(self) -> list[str]:
        """Return active server names without causing any connection."""
        return sorted(self._active)

    def activate(self, server_name: str) -> list[MCPToolDescriptor]:
        """Start one MCP session and discover its tools on explicit activation."""
        self._close_idle_sessions()
        self._refresh_server_for_activation(server_name)
        server = self.server_config(server_name)
        if server_name in self._active:
            return list(self._descriptors.get(server_name, ()))
        try:
            session = self._sessions.get_or_create(server)
            descriptors = self._descriptors_from_items(server, session.list_tools())
            self._descriptors[server_name] = descriptors
            self._active.add(server_name)
            self._errors.pop(server_name, None)
            return list(descriptors)
        except Exception as exc:  # noqa: BLE001 - preserve error for status diagnostics
            self._errors[server_name] = f"{type(exc).__name__}: {exc}"
            raise

    def list_mcp_tools(self, server_name: str, *, activate: bool | None = None) -> list[MCPToolDescriptor]:
        """发现并返回指定 MCP server 暴露的工具描述。"""
        server = self.server_config(server_name)
        if activate is None:
            activate = self.settings.lifecycle == "eager"
        if activate:
            return self.activate(server_name)
        if server_name in self._descriptors:
            return list(self._descriptors[server_name])
        # A statically declared schema is safe to expose without creating a
        # process or opening a socket. The actual client is still lazy.
        return self._descriptors_from_items(
            server,
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "is_destructive": tool.is_destructive,
                    "approval_mode": tool.approval_mode,
                }
                for tool in server.tools
            ],
        )

    def discover_tools(self) -> list[MCPToolDescriptor]:
        """遍历所有 MCP server，收集它们暴露的工具描述。"""
        tools: list[MCPToolDescriptor] = []
        for server_name in self.server_names():
            try:
                server = self.server_config(server_name)
                if self.settings.lifecycle == "eager":
                    tools.extend(self.list_mcp_tools(server_name, activate=True))
                elif self.settings.direct_tools or server.transport == "mock":
                    # Local mock descriptors are safe test/demo metadata. A
                    # non-mock server must be explicitly opted in before its
                    # static declarations become callable.
                    tools.extend(self.list_mcp_tools(server_name, activate=False))
            except Exception:
                # 单个外部 server 不可用时不阻断其他能力发现。
                continue
        return tools

    def discover_resources(self) -> list[MCPResourceDescriptor]:
        descriptors: list[MCPResourceDescriptor] = []
        for server_name in self.server_names():
            server = self.server_config(server_name)
            # Resource discovery is an explicit SDK operation, so it may
            # activate a server. Status reporting never calls this method.
            self.activate(server_name)
            for item in self._sessions.get_or_create(server).list_resources():
                descriptors.append(MCPResourceDescriptor(server.name, str(item["uri"]), str(item.get("name") or item["uri"]), str(item.get("description") or ""), str(item.get("mime_type") or item.get("mimeType") or ""), server.is_remote, server.requires_auth, {"transport": server.transport}))
        return descriptors

    def discover_prompts(self) -> list[MCPPromptDescriptor]:
        descriptors: list[MCPPromptDescriptor] = []
        for server_name in self.server_names():
            server = self.server_config(server_name)
            self.activate(server_name)
            for item in self._sessions.get_or_create(server).list_prompts():
                descriptors.append(MCPPromptDescriptor(server.name, str(item["name"]), str(item.get("description") or ""), dict(item.get("arguments_schema") or item.get("argumentsSchema") or {}), server.is_remote, server.requires_auth, {"transport": server.transport}))
        return descriptors

    def read_resource(self, server_name: str, uri: str) -> MCPResult:
        server = self.server_config(server_name)
        self.activate(server_name)
        payload = self._sessions.get_or_create(server).client.read_resource(uri)
        return MCPResult(server_name, "mcp_resource", uri, str(payload.get("content") or ""), dict(payload.get("payload") or {}), bool(payload.get("is_error")), {"transport": server.transport})

    def get_prompt(self, server_name: str, name: str, arguments: dict[str, Any] | None = None) -> MCPResult:
        server = self.server_config(server_name)
        self.activate(server_name)
        payload = self._sessions.get_or_create(server).client.get_prompt(name, arguments or {})
        return MCPResult(server_name, "mcp_prompt", name, str(payload.get("content") or ""), dict(payload.get("payload") or {}), bool(payload.get("is_error")), {"transport": server.transport})

    def status_report(self) -> dict[str, Any]:
        """Return server lifecycle, discovery, auth, and transport status for diagnostics."""
        servers: list[dict[str, Any]] = []
        for server_name in self.server_names():
            server = self.server_config(server_name)
            static_tools = self.list_mcp_tools(server_name, activate=False)
            active = self.is_active(server_name)
            item: dict[str, Any] = {
                "name": server.name,
                "transport": server.transport,
                "is_remote": server.is_remote,
                "requires_auth": server.requires_auth,
                "approval_mode": server.approval_mode,
                "status": "ready" if active or (server.transport == "mock" and static_tools) else "configured",
                "active": active,
                "activation_required": not active and server.transport != "mock",
                "tool_count": len(static_tools),
                "error": "",
            }
            item["tools"] = [tool.name for tool in static_tools]
            if server_name in self._errors:
                item["status"] = "error"
                item["error"] = self._errors[server_name]
            servers.append(item)
        return {
            "tool_prefix": self.tool_prefix,
            "server_count": len(servers),
            "ready_count": sum(1 for item in servers if item["status"] in {"ready", "declared"}),
            "active_count": sum(1 for item in servers if item["active"]),
            "servers": servers,
        }

    def call_mcp_tool(self, server_name: str, name: str, arguments: dict[str, Any]) -> MCPResult:
        """找到目标 MCP session，调用指定外部工具并包装成 MCPResult。"""
        self._close_idle_sessions()
        server = self.server_config(server_name)
        if not self.is_active(server_name) and server.transport != "mock":
            raise RuntimeError(
                f"MCP server '{server_name}' is not active; obtain approval for mcp_activate first."
            )
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
        closed = self._sessions.close_all_sessions()
        for server_name in closed:
            self._active.discard(server_name)
            self._descriptors.pop(server_name, None)
        return closed

    def _close_idle_sessions(self) -> list[str]:
        closed = self._sessions.close_idle_sessions(self.settings.idle_timeout)
        for server_name in closed:
            self._active.discard(server_name)
            self._descriptors.pop(server_name, None)
        return closed

    def _refresh_server_for_activation(self, server_name: str) -> None:
        """Make an inactive server match the configuration used by the approval preview."""
        if self._workspace is None:
            return
        document = load_mcp_config(self._workspace, config_paths=self._config_paths)
        refreshed = _server_map(document.servers)
        current = refreshed.get(server_name)
        if current is None:
            raise ValueError(f"Configured MCP server was not found: {server_name}")
        if server_name in self._active:
            if self._servers.get(server_name) != current:
                raise RuntimeError(
                    f"MCP server '{server_name}' changed after activation; close it and obtain a new approval."
                )
            return

        # Preserve active sessions as the original approved process/connection,
        # while refreshing inactive declarations to the current reviewed file.
        for active_name in self._active:
            if active_name in self._servers:
                refreshed[active_name] = self._servers[active_name]
        self._servers = refreshed

    @staticmethod
    def _descriptors_from_items(
        server: MCPServerConfig,
        items: list[dict[str, Any]],
    ) -> list[MCPToolDescriptor]:
        descriptors: list[MCPToolDescriptor] = []
        for item in items:
            if not item.get("name"):
                continue
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
                    metadata={"transport": server.transport, "activation_required": server.transport != "mock"},
                )
            )
        return descriptors


def _server_map(servers: list[MCPServerConfig]) -> dict[str, MCPServerConfig]:
    mapped: dict[str, MCPServerConfig] = {}
    for server in servers:
        if server.name in mapped:
            raise ValueError(f"Duplicate MCP server name: {server.name}")
        mapped[server.name] = server
    return mapped
