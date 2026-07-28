"""统一组装 Agent 运行所需的配置、模型、工具、记忆和存储。"""
from __future__ import annotations

from pathlib import Path

from codemuse.app.extensions_runtime import ExtensionCapabilityDiscoveryProvider, ExtensionRuntime
from codemuse.app.skills_runtime import SkillCapabilityDiscoveryProvider, SkillRuntime
from codemuse.capabilities import CapabilityCatalog, ToolCapabilityDiscoveryProvider
from codemuse.browser.tools import register_browser_tools
from codemuse.config.manager import config_for_workspace
from codemuse.config.schema import CodeMuseConfig
from codemuse.config.patch import merge_patch
from codemuse.llm.registry import create_llm_provider
from codemuse.learning.runtime import LearningRuntime
from codemuse.memory.file_memory_tools import register_file_memory_tools
from codemuse.memory.retrieval_hook import MemoryContextProvider
from codemuse.mcp.adapter import register_mcp_tools
from codemuse.mcp.manager import MCPManager
from codemuse.runtime.runtime import AgentRuntime
from codemuse.runtime.hooks import RuntimeHooks
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.storage.checkpoints import CheckpointStore
from codemuse.storage.sessions import SessionStore
from codemuse.storage.timeline import TimelineStore
from codemuse.session.session_config import SessionConfigStore
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

Tool-use policy v3:
- Answer normal questions directly. Do not inspect files, run commands, call web tools, or use memory merely to be proactive.
- Use tools only when the user asks for workspace or external information, requests a change or command, or the answer cannot be reliable without evidence from the workspace.
- When tools are needed, use the smallest useful set. For repository inspection, start from one broad root-level observation and expand only paths needed for the answer; avoid repeated calls, no more than four distinct calls in one response, and no more than eight calls for one user task.
- When the user asks to learn from a repository, summarize the minimal architecture blueprint. Save blueprint or project memory only when the user explicitly asks to remember it, or when a completed task establishes a clearly durable project fact.
- Use save_project_memory for concise durable memories and search_project_memory only when prior project knowledge is likely relevant.
"""


def create_tool_registry(
    workspace: Path,
    *,
    session_store: SessionStore | None = None,
    config: CodeMuseConfig | None = None,
    skill_runtime: SkillRuntime | None = None,
    extension_runtime: ExtensionRuntime | None = None,
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
        register_browser_tools(registry, workspace)
    if config.capabilities.memory_enabled:
        register_file_memory_tools(registry, workspace)
    if config.capabilities.skills_enabled:
        register_skill_tools(registry, workspace, skill_runtime or SkillRuntime(workspace))
    if config.capabilities.extensions_enabled:
        register_extension_tools(registry, workspace, extension_runtime or ExtensionRuntime(workspace))
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
    skill_runtime = SkillRuntime(workspace)
    extension_runtime = ExtensionRuntime(workspace)
    registry = create_tool_registry(workspace, session_store=session_store, config=config, skill_runtime=skill_runtime, extension_runtime=extension_runtime)
    providers = [ToolCapabilityDiscoveryProvider(registry)]
    if config.capabilities.skills_enabled:
        providers.append(SkillCapabilityDiscoveryProvider(skill_runtime))
    if config.capabilities.extensions_enabled:
        providers.append(ExtensionCapabilityDiscoveryProvider(extension_runtime))
    return CapabilityCatalog(providers)


def build_agent(workspace: Path, *, session_id: str | None = None) -> AgentRuntime:
    """按 workspace 配置组装完整 AgentRuntime。"""
    workspace = workspace.resolve()
    config = config_for_workspace(workspace)
    if session_id:
        session_patch = SessionConfigStore(workspace).config_patch(session_id)
        if session_patch:
            config = CodeMuseConfig.from_dict(merge_patch(config.to_dict(), session_patch))
    data_root = workspace / ".data" / "codemuse"
    session_store = SessionStore(data_root / "sessions")
    approval_store = PendingApprovalStore(data_root / "approvals")
    checkpoint_store = CheckpointStore(data_root / "checkpoints")
    timeline_store = TimelineStore(data_root / "timeline")
    if session_id:
        session = session_store.load(session_id)
        if "Tool-use policy v3" not in session.system_prompt:
            session.system_prompt = DEFAULT_SYSTEM_PROMPT
            session_store.save(session)
    else:
        session = session_store.create(DEFAULT_SYSTEM_PROMPT)
        session_store.save(session)
    skill_runtime = SkillRuntime(workspace)
    extension_runtime = ExtensionRuntime(workspace)
    hooks = RuntimeHooks()
    learning_runtime = LearningRuntime(workspace, session_store=session_store)
    hooks.lifecycle_event_hooks.append(learning_runtime.handle_event)
    if config.capabilities.skills_enabled:
        hooks.add_transform_context_hook("skills", "skill", skill_runtime.transform_context)
    if config.capabilities.extensions_enabled:
        extension_runtime.install_hooks(hooks)
    registry = create_tool_registry(
        workspace,
        session_store=session_store,
        config=config,
        skill_runtime=skill_runtime,
        extension_runtime=extension_runtime,
    )
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
        max_tool_calls_per_turn=config.runtime.max_tool_calls_per_turn,
        max_tool_calls_per_prompt=config.runtime.max_tool_calls_per_prompt,
        history_token_budget=config.runtime.history_token_budget,
        tools_enabled=config.runtime.tools_enabled,
        hooks=hooks,
    )

