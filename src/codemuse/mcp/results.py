"""实现 mcp/results.py 对应的业务边界和辅助逻辑。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MCPResultKind = Literal["mcp_tool", "mcp_resource", "mcp_prompt"]


@dataclass
class MCPResult:
    """MCP 调用的统一结果。

    Runtime 不直接认识 MCP 协议；Adapter 会把 MCPResult 再转成普通 ToolResult。
    """

    server_name: str
    kind: MCPResultKind
    name_or_uri: str
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
