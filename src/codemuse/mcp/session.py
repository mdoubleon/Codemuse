"""实现 mock MCP client 和 MCP 会话管理，为后续真实传输预留位置。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from string import Formatter
from typing import Protocol

from codemuse.mcp.config import MCPServerConfig, MCPToolConfig


class MCPClientProtocol(Protocol):
    """定义 MCP 客户端需要实现的工具发现和调用协议。"""
    def initialize(self) -> None:
        """初始化 MCP client/session，在 mock 实现中为后续调用预留状态。"""
        ...

    def list_tools(self) -> list[dict]:
        """列出工具名、分类、权限域和副作用等调试信息。"""
        ...

    def call_tool(self, name: str, arguments: dict) -> dict:
        """在 MCP client 中执行指定工具，并返回原始 MCP 响应字典。"""
        ...

    def close(self) -> None:
        """释放该对象持有的工作线程、会话或连接资源。"""
        ...


class MockMCPClient:
    """配置驱动的本地 mock MCP client。

    它不是真实 MCP 传输层，只是 Stage 8 用来打通发现和适配链路的教学版。
    """

    def __init__(self, server: MCPServerConfig) -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        self.server = server
        self._tools = {tool.name: tool for tool in server.tools}

    def initialize(self) -> None:
        """初始化 MCP client/session，在 mock 实现中为后续调用预留状态。"""
        return None

    def list_tools(self) -> list[dict]:
        """列出工具名、分类、权限域和副作用等调试信息。"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "is_destructive": tool.is_destructive,
                "approval_mode": tool.approval_mode,
            }
            for tool in self.server.tools
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        """在 MCP client 中执行指定工具，并返回原始 MCP 响应字典。"""
        if name not in self._tools:
            return {
                "content": f"Unknown MCP tool: {name}",
                "payload": {"arguments": arguments},
                "is_error": True,
            }
        tool = self._tools[name]
        return {
            "content": self._render_tool_content(tool, arguments),
            "payload": {"arguments": arguments},
            "is_error": False,
        }

    def close(self) -> None:
        """释放该对象持有的工作线程、会话或连接资源。"""
        return None

    def _render_tool_content(self, tool: MCPToolConfig, arguments: dict) -> str:
        """根据工具配置和调用参数生成 mock MCP 工具返回文本。"""
        if tool.response_template:
            return _safe_format(tool.response_template, arguments)
        if tool.response:
            return tool.response
        return json.dumps({"server": self.server.name, "tool": tool.name, "arguments": arguments}, ensure_ascii=False)


@dataclass
class MCPSession:
    """绑定 MCP server 描述和客户端实例的会话对象。"""
    server: MCPServerConfig
    client: MCPClientProtocol
    last_used_at: float
    discovery_cache: dict[str, list[dict]] = field(default_factory=dict)

    def touch(self, now: float) -> None:
        """更新 MCP session 的最近使用时间。"""
        self.last_used_at = now

    def list_tools(self) -> list[dict]:
        """列出工具名、分类、权限域和副作用等调试信息。"""
        if "tools" not in self.discovery_cache:
            self.discovery_cache["tools"] = self.client.list_tools()
        return [dict(item) for item in self.discovery_cache["tools"]]


class MCPSessionManager:
    """按 server 懒加载 MCP session。

    当前实现先支持 mock transport，后续真实 stdio/http 连接也从这里集中管理生命周期。
    """

    def __init__(self) -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self._sessions: dict[str, MCPSession] = {}

    def get_or_create(self, server: MCPServerConfig) -> MCPSession:
        """按 server 名称获取或创建 MCP 会话。"""
        session = self._sessions.get(server.name)
        if session is not None:
            session.touch(time.time())
            return session
        if server.transport != "mock":
            raise NotImplementedError(f"CodeMuse currently supports mock MCP transport only: {server.transport}")
        client = MockMCPClient(server)
        client.initialize()
        session = MCPSession(server=server, client=client, last_used_at=time.time())
        self._sessions[server.name] = session
        return session

    def close_all_sessions(self) -> list[str]:
        """关闭管理器中缓存的所有 MCP session。"""
        closed: list[str] = []
        for name, session in list(self._sessions.items()):
            session.client.close()
            del self._sessions[name]
            closed.append(name)
        return closed


def _safe_format(template: str, arguments: dict) -> str:
    """生成安全可控的内部表示，避免路径或名称越界。"""
    values = {field_name: str(arguments.get(field_name, "")) for _, field_name, _, _ in Formatter().parse(template) if field_name}
    return template.format(**values)
