"""导出 MCP 配置、管理器和工具适配能力。"""

from codemuse.mcp.adapter import MCPToolAdapter, public_mcp_tool_name, register_mcp_tools
from codemuse.mcp.config import MCPConfigDocument, MCPPromptConfig, MCPResourceConfig, MCPServerConfig, MCPToolConfig, MCPTransportSettings, load_mcp_config
from codemuse.mcp.descriptors import MCPPromptDescriptor, MCPResourceDescriptor, MCPToolDescriptor
from codemuse.mcp.manager import MCPManager
from codemuse.mcp.results import MCPResult

__all__ = [
    "MCPConfigDocument",
    "MCPManager",
    "MCPPromptConfig",
    "MCPPromptDescriptor",
    "MCPResourceConfig",
    "MCPResourceDescriptor",
    "MCPResult",
    "MCPServerConfig",
    "MCPToolAdapter",
    "MCPToolConfig",
    "MCPToolDescriptor",
    "MCPTransportSettings",
    "load_mcp_config",
    "public_mcp_tool_name",
    "register_mcp_tools",
]
