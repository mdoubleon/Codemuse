"""实现 mock、stdio 和 HTTP JSON-RPC MCP 客户端及其会话生命周期。"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
import urllib.error
import urllib.request
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
    """配置驱动的本地 mock MCP client，用于离线测试和演示。"""

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

    def list_resources(self) -> list[dict]:
        return [{"uri": item.uri, "name": item.name, "description": item.description, "mime_type": item.mime_type} for item in self.server.resources]

    def read_resource(self, uri: str) -> dict:
        resource = next((item for item in self.server.resources if item.uri == uri), None)
        if resource is None:
            raise ValueError(f"Unknown MCP resource: {uri}")
        return {"content": resource.content, "payload": {"uri": uri, "mime_type": resource.mime_type}, "is_error": False}

    def list_prompts(self) -> list[dict]:
        return [{"name": item.name, "description": item.description, "arguments_schema": item.arguments_schema} for item in self.server.prompts]

    def get_prompt(self, name: str, arguments: dict) -> dict:
        prompt = next((item for item in self.server.prompts if item.name == name), None)
        if prompt is None:
            raise ValueError(f"Unknown MCP prompt: {name}")
        return {"content": _safe_format(prompt.template, arguments), "payload": {"name": name, "arguments": arguments}, "is_error": False}

    def _render_tool_content(self, tool: MCPToolConfig, arguments: dict) -> str:
        """根据工具配置和调用参数生成 mock MCP 工具返回文本。"""
        if tool.response_template:
            return _safe_format(tool.response_template, arguments)
        if tool.response:
            return tool.response
        return json.dumps({"server": self.server.name, "tool": tool.name, "arguments": arguments}, ensure_ascii=False)


class StdioMCPClient:
    """Minimal MCP JSON-RPC client over a newline-delimited stdio process."""

    def __init__(self, server: MCPServerConfig) -> None:
        if not server.command:
            raise ValueError(f"MCP stdio server has no command: {server.name}")
        command = [*shlex.split(server.command), *server.args]
        self.server = server
        self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._next_id = 0

    def initialize(self) -> None:
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "codemuse", "version": "1"}})
        self._notify("notifications/initialized", {})

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {})
        return list((result.get("tools") if isinstance(result, dict) else []) or [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content") if isinstance(result, dict) else result
        return {"content": _content_text(content), "payload": result, "is_error": bool(result.get("isError")) if isinstance(result, dict) else False}

    def list_resources(self) -> list[dict]:
        return list(self._request("resources/list", {}).get("resources") or [])

    def read_resource(self, uri: str) -> dict:
        result = self._request("resources/read", {"uri": uri})
        return {"content": _content_text(result.get("contents")), "payload": result, "is_error": False}

    def list_prompts(self) -> list[dict]:
        return list(self._request("prompts/list", {}).get("prompts") or [])

    def get_prompt(self, name: str, arguments: dict) -> dict:
        result = self._request("prompts/get", {"name": name, "arguments": arguments})
        return {"content": _content_text(result.get("messages")), "payload": result, "is_error": False}

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if self._process.stdout is None:
            raise RuntimeError("MCP stdio stdout is unavailable")
        deadline = time.time() + max(1, self.server.timeout_seconds)
        while time.time() < deadline:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP stdio process exited: {self.server.name}")
            payload = json.loads(line.decode("utf-8"))
            if payload.get("id") != request_id:
                continue
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            return dict(payload.get("result") or {})
        raise TimeoutError(f"MCP request timed out: {self.server.name}/{method}")

    def _write(self, payload: dict) -> None:
        if self._process.stdin is None:
            raise RuntimeError("MCP stdio stdin is unavailable")
        self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self._process.stdin.flush()


class HTTPMCPClient:
    """Minimal MCP JSON-RPC client for HTTP/streamable HTTP endpoints."""

    def __init__(self, server: MCPServerConfig) -> None:
        if not server.url:
            raise ValueError(f"MCP HTTP server has no url: {server.name}")
        self.server = server
        self._next_id = 0

    def initialize(self) -> None:
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "codemuse", "version": "1"}})
        self._notify("notifications/initialized", {})

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {})
        return list((result.get("tools") if isinstance(result, dict) else []) or [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content") if isinstance(result, dict) else result
        return {"content": _content_text(content), "payload": result, "is_error": bool(result.get("isError")) if isinstance(result, dict) else False}

    def list_resources(self) -> list[dict]:
        return list(self._request("resources/list", {}).get("resources") or [])

    def read_resource(self, uri: str) -> dict:
        result = self._request("resources/read", {"uri": uri})
        return {"content": _content_text(result.get("contents")), "payload": result, "is_error": False}

    def list_prompts(self) -> list[dict]:
        return list(self._request("prompts/list", {}).get("prompts") or [])

    def get_prompt(self, name: str, arguments: dict) -> dict:
        result = self._request("prompts/get", {"name": name, "arguments": arguments})
        return {"content": _content_text(result.get("messages")), "payload": result, "is_error": False}

    def close(self) -> None:
        return None

    def _notify(self, method: str, params: dict) -> None:
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.server.url or "", data=payload, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=max(1, self.server.timeout_seconds)):
            return None

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.server.url or "", data=payload, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=max(1, self.server.timeout_seconds)) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            exc.close()
            raise RuntimeError(f"MCP HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MCP HTTP request failed: {exc.reason}") from exc
        result = json.loads(body)
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return dict(result.get("result") or {})


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(content or {}, ensure_ascii=False)


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


    def list_resources(self) -> list[dict]:
        if "resources" not in self.discovery_cache:
            self.discovery_cache["resources"] = self.client.list_resources()
        return [dict(item) for item in self.discovery_cache["resources"]]

    def list_prompts(self) -> list[dict]:
        if "prompts" not in self.discovery_cache:
            self.discovery_cache["prompts"] = self.client.list_prompts()
        return [dict(item) for item in self.discovery_cache["prompts"]]


class MCPSessionManager:
    """按 server 懒加载并集中管理 mock、stdio 和 HTTP MCP session。"""

    def __init__(self) -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self._sessions: dict[str, MCPSession] = {}

    def get_or_create(self, server: MCPServerConfig) -> MCPSession:
        """按 server 名称获取或创建 MCP 会话。"""
        session = self._sessions.get(server.name)
        if session is not None:
            session.touch(time.time())
            return session
        if server.transport == "mock":
            client = MockMCPClient(server)
        elif server.transport == "stdio":
            client = StdioMCPClient(server)
        elif server.transport in {"http", "streamable_http", "sse"}:
            client = HTTPMCPClient(server)
        else:
            raise ValueError(f"Unsupported MCP transport: {server.transport}")
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
