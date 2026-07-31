"""读取 mcp.json 并解析为 MCP server、transport 和 tool 配置。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MCPTransportSettings:
    """MCPTransportSettings：保存该能力运行需要的配置字段。"""
    tool_prefix: str = "mcp"
    idle_timeout: int = 300
    lifecycle: str = "lazy"
    direct_tools: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "MCPTransportSettings":
        data = dict(payload or {})
        unknown = set(data) - {"tool_prefix", "idle_timeout", "lifecycle", "direct_tools"}
        if unknown:
            raise ValueError(f"Unknown MCP settings field: {sorted(unknown)[0]}")
        tool_prefix = str(data.get("tool_prefix") or "mcp").strip()
        if not tool_prefix:
            raise ValueError("MCP settings.tool_prefix cannot be empty")
        lifecycle = str(data.get("lifecycle") or "lazy").strip().lower()
        if lifecycle not in {"lazy", "eager"}:
            raise ValueError("MCP settings.lifecycle must be 'lazy' or 'eager'")
        idle_timeout = data.get("idle_timeout", 300)
        if isinstance(idle_timeout, bool) or not isinstance(idle_timeout, int) or not 1 <= idle_timeout <= 86_400:
            raise ValueError("MCP settings.idle_timeout must be an integer between 1 and 86400")
        direct_tools = data.get("direct_tools", False)
        if not isinstance(direct_tools, bool):
            raise ValueError("MCP settings.direct_tools must be a boolean")
        return cls(
            tool_prefix=tool_prefix,
            idle_timeout=idle_timeout,
            lifecycle=lifecycle,
            direct_tools=direct_tools,
        )


@dataclass
class MCPToolConfig:
    """MCPToolConfig：保存该能力运行需要的配置字段。"""
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    response: str = ""
    response_template: str = ""
    is_destructive: bool = False
    approval_mode: str = "default"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MCPToolConfig":
        """把字典里的字段校正并恢复成 MCPToolConfig 对象。"""
        schema = payload.get("input_schema") or payload.get("inputSchema") or {}
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            input_schema=dict(schema),
            response=str(payload.get("response") or ""),
            response_template=str(payload.get("response_template") or payload.get("responseTemplate") or ""),
            is_destructive=bool(payload.get("is_destructive") or payload.get("destructive")),
            approval_mode=str(payload.get("approval_mode") or "default"),
        )


@dataclass
class MCPResourceConfig:
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = "text/plain"
    content: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MCPResourceConfig":
        return cls(
            uri=str(payload["uri"]),
            name=str(payload.get("name") or payload["uri"]),
            description=str(payload.get("description") or ""),
            mime_type=str(payload.get("mime_type") or payload.get("mimeType") or "text/plain"),
            content=str(payload.get("content") or ""),
        )


@dataclass
class MCPPromptConfig:
    name: str
    description: str = ""
    arguments_schema: dict[str, Any] = field(default_factory=dict)
    template: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MCPPromptConfig":
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            arguments_schema=dict(payload.get("arguments_schema") or payload.get("argumentsSchema") or {}),
            template=str(payload.get("template") or ""),
        )


@dataclass
class MCPServerConfig:
    """MCPServerConfig：保存该能力运行需要的配置字段。"""
    name: str
    description: str = ""
    transport: str = "mock"
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    is_remote: bool = False
    requires_auth: bool = False
    approval_mode: str = "default"
    timeout_seconds: int = 30
    tools: list[MCPToolConfig] = field(default_factory=list)
    resources: list[MCPResourceConfig] = field(default_factory=list)
    prompts: list[MCPPromptConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MCPServerConfig":
        """把字典里的字段校正并恢复成 MCPServerConfig 对象。"""
        tools = [MCPToolConfig.from_dict(item) for item in payload.get("tools", [])]
        resources = [MCPResourceConfig.from_dict(item) for item in payload.get("resources", [])]
        prompts = [MCPPromptConfig.from_dict(item) for item in payload.get("prompts", [])]
        return cls(
            name=str(payload["name"]),
            description=str(payload.get("description") or ""),
            transport=str(payload.get("transport") or "mock"),
            url=payload.get("url"),
            command=payload.get("command"),
            args=[str(item) for item in payload.get("args", [])],
            is_remote=bool(payload.get("is_remote") or payload.get("url")),
            requires_auth=bool(payload.get("requires_auth")),
            approval_mode=str(payload.get("approval_mode") or "default"),
            timeout_seconds=int(payload.get("timeout_seconds") or 30),
            tools=tools,
            resources=resources,
            prompts=prompts,
        )


@dataclass
class MCPConfigDocument:
    """保存一个 workspace 解析后的 MCP 配置文档。"""
    settings: MCPTransportSettings = field(default_factory=MCPTransportSettings)
    servers: list[MCPServerConfig] = field(default_factory=list)


def load_mcp_config(workspace: Path, config_paths: list[Path] | None = None) -> MCPConfigDocument:
    """读取 MCP 配置；外部连接仍由会话管理器按需建立。"""

    paths = config_paths or [
        workspace / "mcp.json",
        workspace / ".codemuse" / "mcp.json",
    ]
    document = MCPConfigDocument()
    for path in paths:
        if not path.exists():
            continue
        loaded = _parse_mcp_document(path)
        document.settings = loaded.settings
        document.servers.extend(loaded.servers)
    _assert_unique_server_names(document.servers)
    return document


def load_mcp_server_configs(workspace: Path, config_paths: list[Path] | None = None) -> list[MCPServerConfig]:
    """读取 MCP 配置文档，并只返回 server 配置列表。"""
    return load_mcp_config(workspace, config_paths=config_paths).servers


def _parse_mcp_document(path: Path) -> MCPConfigDocument:
    """解析输入数据并返回结构化结果。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return MCPConfigDocument(servers=[MCPServerConfig.from_dict(item) for item in data])
    if not isinstance(data, dict):
        raise ValueError(f"MCP config must be a list or object: {path}")

    raw_settings = data.get("settings", {})
    if not isinstance(raw_settings, dict):
        raise ValueError(f"MCP settings must be an object: {path}")
    settings = MCPTransportSettings.from_dict(raw_settings)
    if isinstance(data.get("mcpServers"), dict):
        raw_servers = []
        for name, value in data["mcpServers"].items():
            item = dict(value)
            item.setdefault("name", name)
            raw_servers.append(item)
    else:
        raw_servers = data.get("servers", [])
    return MCPConfigDocument(settings=settings, servers=[MCPServerConfig.from_dict(item) for item in raw_servers])


def _assert_unique_server_names(servers: list[MCPServerConfig]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for server in servers:
        if server.name in seen:
            duplicates.add(server.name)
        seen.add(server.name)
    if duplicates:
        raise ValueError(f"Duplicate MCP server name: {sorted(duplicates)[0]}")
