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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MCPServerConfig":
        """把字典里的字段校正并恢复成 MCPServerConfig 对象。"""
        tools = [MCPToolConfig.from_dict(item) for item in payload.get("tools", [])]
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
        )


@dataclass
class MCPConfigDocument:
    """保存一个 workspace 解析后的 MCP 配置文档。"""
    settings: MCPTransportSettings = field(default_factory=MCPTransportSettings)
    servers: list[MCPServerConfig] = field(default_factory=list)


def load_mcp_config(workspace: Path, config_paths: list[Path] | None = None) -> MCPConfigDocument:
    """读取 CodeMuse 的 MCP 配置。

    当前阶段只解析配置，不启动真实外部进程。这样先学清楚 MCP 在架构中的位置。
    """

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

    settings = MCPTransportSettings(**dict(data.get("settings", {})))
    if isinstance(data.get("mcpServers"), dict):
        raw_servers = []
        for name, value in data["mcpServers"].items():
            item = dict(value)
            item.setdefault("name", name)
            raw_servers.append(item)
    else:
        raw_servers = data.get("servers", [])
    return MCPConfigDocument(settings=settings, servers=[MCPServerConfig.from_dict(item) for item in raw_servers])
