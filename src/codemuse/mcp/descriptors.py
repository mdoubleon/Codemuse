"""实现 mcp/descriptors.py 对应的业务边界和辅助逻辑。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPToolDescriptor:
    """MCP 工具描述。

    Descriptor 是“发现阶段”的结果：它告诉 Agent 外部 server 有什么工具，
    但它本身不负责执行工具。
    """

    server_name: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    is_remote: bool = False
    requires_auth: bool = False
    is_destructive: bool = False
    approval_mode: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
