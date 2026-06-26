"""统一组装 Agent 运行所需的配置、模型、工具、记忆和存储。"""
from __future__ import annotations

from pathlib import Path

from codemuse.app.extensions_runtime import ExtensionCapabilityDiscoveryProvider, ExtensionRuntime
from codemuse.app.skills_runtime import SkillCapabilityDiscoveryProvider, SkillRuntime
from codemuse.capabilities import CapabilityCatalog, ToolCapabilityDiscoveryProvider
from codemuse.config.manager import config_for_workspace
from codemuse.config.schema import CodeMuseConfig
from codemuse.llm.registry import create_llm_provider
from codemuse.memory.file_memory_tools import register_file_memory_tools
from codemuse.memory.retrieval_hook import MemoryContextProvider
from codemuse.mcp.adapter import register_mcp_tools
from codemuse.mcp.manager import MCPManager
from codemuse.runtime.runtime import AgentRuntime
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.storage.checkpoints import CheckpointStore
from codemuse.storage.sessions import SessionStore
from codemuse.storage.timeline import TimelineStore
from codemuse.subagents.manager import SubAgentManager
from codemuse.tools.file_tools import register_coding_tools
from codemuse.tools.extension_tool import register_extension_tools
from codemuse.tools.repo_tools import register_repo_tools
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.shell_tool import register_shell_tools
from codemuse.tools.skill_tool import register_skill_tools
from codemuse.tools.subagent_tool import register_subagent_tools
from codemuse.web_tools.tools import register_web_tools

DEFAULT_SYSTEM_PROMPT = """You are CodeMuse, a coding agent that can inspect a workspace with tools.
When the user wants to learn from a repository, summarize it into a minimal architecture blueprint and save searchable blueprint memory.
Use save_project_memory when the user explicitly asks you to remember something, or when you learn durable project facts, preferences, architecture decisions, workflows, or constraints that should be reused in future turns. Keep saved memories concise and specific.
Use search_project_memory when prior project knowledge may help answer the current request."""


def create_tool_registry(
    workspace: Path,
    *,
    session_store: SessionStore | None = None,
    config: CodeMuseConfig | None = None,
) -> ToolRegistry:
    """根据 workspace 和配置创建 ToolRegistry，并注册当前可用工具。"""
    workspace = workspace.resolve()
    config = config or config_for_workspace(workspace)
    session_store = session_store or SessionStore(workspace / ".data" / "codemuse" / "sessions")
    registry = ToolRegistry(workspace)
    register_coding_tools(registry, workspace)
    register_shell_tools(registry, workspace)
    register_repo_tools(registry, workspace)
    if config.capabilities.web_enabled:
        register_web_tools(registry, workspace)
    if config.capabilities.memory_enabled:
        register_file_memory_tools(registry, workspace)
    if config.capabilities.skills_enabled:
        register_skill_tools(registry, workspace, SkillRuntime(workspace))
    if config.capabilities.extensions_enabled:
        register_extension_tools(registry, workspace, ExtensionRuntime(workspace))
    if config.capabilities.mcp_enabled:
        # MCP 是外部能力入口，但进入 Runtime 前仍然要统一注册成普通工具。
        mcp_manager = MCPManager.from_workspace(workspace)
        register_mcp_tools(registry, workspace, mcp_manager)
    if config.capabilities.subagents_enabled:
        # Subagent 通过工具进入主 Runtime，但子 Agent 自己只能拿到 allowlist 工具。
        subagent_manager = SubAgentManager(
            workspace=workspace,
            parent_registry=registry,
            session_store=session_store,
            llm_factory=lambda config=config: create_llm_provider(config.model),
        )
        register_subagent_tools(registry, workspace, subagent_manager)
    return registry


def create_capability_catalog(workspace: Path) -> CapabilityCatalog:
    """先构建 ToolRegistry，再把已加载工具转成能力清单。"""
    workspace = workspace.resolve()
    config = config_for_workspace(workspace)
    session_store = SessionStore(workspace / ".data" / "codemuse" / "sessions")
    registry = create_tool_registry(workspace, session_store=session_store, config=config)
    providers = [ToolCapabilityDiscoveryProvider(registry)]
    if config.capabilities.skills_enabled:
        providers.append(SkillCapabilityDiscoveryProvider(SkillRuntime(workspace)))
    if config.capabilities.extensions_enabled:
        providers.append(ExtensionCapabilityDiscoveryProvider(ExtensionRuntime(workspace)))
    return CapabilityCatalog(providers)


def build_agent(workspace: Path, *, session_id: str | None = None) -> AgentRuntime:
    """按 workspace 配置组装完整 AgentRuntime。"""
    workspace = workspace.resolve()
    config = config_for_workspace(workspace)
    data_root = workspace / ".data" / "codemuse"
    session_store = SessionStore(data_root / "sessions")
    approval_store = PendingApprovalStore(data_root / "approvals")
    checkpoint_store = CheckpointStore(data_root / "checkpoints")
    timeline_store = TimelineStore(data_root / "timeline")
    if session_id:
        session = session_store.load(session_id)
        if "save_project_memory" not in session.system_prompt or "search_project_memory" not in session.system_prompt:
            session.system_prompt = DEFAULT_SYSTEM_PROMPT
            session_store.save(session)
    else:
        session = session_store.create(DEFAULT_SYSTEM_PROMPT)
        session_store.save(session)
    registry = create_tool_registry(workspace, session_store=session_store, config=config)
    memory_provider = MemoryContextProvider(workspace=workspace) if config.capabilities.memory_enabled else None
    return AgentRuntime(
        workspace=workspace,
        llm=create_llm_provider(config.model),
        tool_registry=registry,
        session_store=session_store,
        session=session,
        memory_provider=memory_provider,
        approval_store=approval_store,
        checkpoint_store=checkpoint_store,
        timeline_store=timeline_store,
        max_turns=config.runtime.max_turns,
    )

