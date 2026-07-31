"""对外提供稳定 Python API，把 CLI 和服务端操作转交给 Runtime。"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codemuse.app.bootstrap import create_capability_catalog
from codemuse.capabilities.descriptor import CapabilityKind
from codemuse.config.manager import get_config_manager
from codemuse.config.patch import merge_patch
from codemuse.config.schema import CodeMuseConfig
from codemuse.llm.registry import get_provider_descriptor
from codemuse.llm.registry import list_llm_providers
from codemuse.llm.registry import provider_readiness
from codemuse.learning.runtime import LearningRuntime
from codemuse.memory.index_pipeline import format_memory_pipeline_search, refresh_memory_index, search_memory_pipeline
from codemuse.mcp.manager import MCPManager
from codemuse.runtime.events import AgentEvent
from codemuse.runtime.runtime import AgentRuntime
from codemuse.runtime.session_host import SessionHost
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.storage.checkpoints import CheckpointStore
from codemuse.storage.sessions import SessionStore, build_session_tree
from codemuse.storage.timeline import TimelineStore
from codemuse.session.session_config import SessionConfigStore

Subscriber = Callable[[AgentEvent], None]

_ENVIRONMENT_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def create_runtime(
    workspace: Path,
    *,
    session_id: str | None = None,
    subscriber: Subscriber | None = None,
    subscribers: list[Subscriber] | None = None,
) -> AgentRuntime:
    """为 SDK 调用者创建或恢复 Runtime，并挂载事件订阅回调。"""

    host = SessionHost()
    runtime = host.restore_session(workspace, session_id) if session_id else host.create_session(workspace)
    # SDK 是外部调用入口；订阅事件后，调用方可以像 Web/CLI 一样观察 Agent 运行过程。
    for callback in _merge_subscribers(subscriber=subscriber, subscribers=subscribers):
        runtime.subscribe(callback)
    return runtime


def run(
    prompt: str,
    workspace: Path,
    *,
    session_id: str | None = None,
    collect_events: bool = False,
    subscriber: Subscriber | None = None,
    subscribers: list[Subscriber] | None = None,
) -> dict[str, Any]:
    """执行一次用户 prompt，并返回会话、事件和状态摘要。"""
    clean = prompt.strip()
    if not clean:
        raise ValueError("Prompt cannot be empty.")
    runtime = create_runtime(workspace, session_id=session_id, subscriber=subscriber, subscribers=subscribers)
    events = runtime.prompt(clean)
    return _result_payload(runtime, events, collect_events=collect_events)


def approve(
    workspace: Path,
    approval_id: str,
    *,
    session_id: str | None = None,
    collect_events: bool = False,
    subscriber: Subscriber | None = None,
    subscribers: list[Subscriber] | None = None,
) -> dict[str, Any]:
    """批准一个等待中的工具调用，并让 Runtime 继续执行。"""
    workspace = workspace.resolve()
    target_session_id = session_id or _approval_store(workspace).load(approval_id).session_id
    runtime = create_runtime(workspace, session_id=target_session_id, subscriber=subscriber, subscribers=subscribers)
    events = runtime.approve(approval_id)
    return _result_payload(runtime, events, collect_events=collect_events)


def reject(
    workspace: Path,
    approval_id: str,
    *,
    session_id: str | None = None,
    collect_events: bool = False,
    subscriber: Subscriber | None = None,
    subscribers: list[Subscriber] | None = None,
) -> dict[str, Any]:
    """拒绝一个等待中的工具调用，并写回会话。"""
    workspace = workspace.resolve()
    target_session_id = session_id or _approval_store(workspace).load(approval_id).session_id
    runtime = create_runtime(workspace, session_id=target_session_id, subscriber=subscriber, subscribers=subscribers)
    events = runtime.reject(approval_id)
    return _result_payload(runtime, events, collect_events=collect_events)


def enqueue_message(
    workspace: Path,
    text: str,
    *,
    session_id: str | None = None,
    delivery: str = "follow_up",
) -> dict[str, Any]:
    """Queue steering/follow-up input without mutating the active turn directly."""
    runtime = create_runtime(workspace, session_id=session_id)
    runtime.enqueue_message(text, delivery=delivery)
    return _result_payload(runtime, [], collect_events=False)


def compact_session(workspace: Path, *, session_id: str | None = None) -> dict[str, Any]:
    """Compact persisted conversation history and return its operation report."""
    runtime = create_runtime(workspace, session_id=session_id)
    result = runtime.compact()
    return {"session_id": runtime.session_id, **result, "state": runtime.state.to_dict()}


def create_checkpoint(
    workspace: Path,
    *,
    session_id: str | None = None,
    label: str = "manual checkpoint",
    collect_events: bool = False,
    subscriber: Subscriber | None = None,
    subscribers: list[Subscriber] | None = None,
) -> dict[str, Any]:
    """为当前会话创建一个可回退检查点。"""
    runtime = create_runtime(workspace, session_id=session_id, subscriber=subscriber, subscribers=subscribers)
    events = runtime.create_checkpoint(label or "manual checkpoint")
    return _result_payload(runtime, events, collect_events=collect_events)


def rewind(
    workspace: Path,
    checkpoint_id: str,
    *,
    session_id: str | None = None,
    mode: str = "conversation_and_workspace",
    collect_events: bool = False,
    subscriber: Subscriber | None = None,
    subscribers: list[Subscriber] | None = None,
) -> dict[str, Any]:
    """将当前会话恢复到指定检查点。"""
    workspace = workspace.resolve()
    target_session_id = session_id or _checkpoint_store(workspace).load(checkpoint_id).session_id
    runtime = create_runtime(workspace, session_id=target_session_id, subscriber=subscriber, subscribers=subscribers)
    events = runtime.rewind(checkpoint_id, mode=mode)
    return _result_payload(runtime, events, collect_events=collect_events)


def preview_rewind(
    workspace: Path,
    checkpoint_id: str,
    *,
    session_id: str | None = None,
    mode: str = "conversation_and_workspace",
) -> dict[str, Any]:
    """Return rewind effects and warnings without mutating any state."""
    workspace = workspace.resolve()
    target_session_id = session_id or _checkpoint_store(workspace).load(checkpoint_id).session_id
    runtime = create_runtime(workspace, session_id=target_session_id)
    return runtime.preview_rewind(checkpoint_id, mode=mode)


def list_sessions(workspace: Path) -> list[dict[str, Any]]:
    """列出 workspace 下保存的所有会话记录。"""
    return [record.to_dict() for record in _session_store(workspace.resolve()).list()]


def list_session_tree(workspace: Path) -> list[dict[str, Any]]:
    """把保存的会话列成嵌套的根节点和子节点。"""
    return build_session_tree(list_sessions(workspace))


def resume_session(workspace: Path, session_id: str) -> dict[str, Any]:
    """Load a persisted session without running a new model turn."""
    return _session_store(workspace.resolve()).load(session_id).to_dict()


def fork_session(
    workspace: Path,
    parent_session_id: str,
    *,
    head_id: str | None = None,
) -> dict[str, Any]:
    """分支一个已保存会话，并返回独立持久化的子会话。"""
    store = _session_store(workspace.resolve())
    child = store.fork_from_head(parent_session_id, head_id) if head_id else store.fork(parent_session_id)
    store.save(child)
    return child.to_dict()


def branch_session(workspace: Path, parent_session_id: str, *, head_id: str | None = None) -> dict[str, Any]:
    """Alias for fork_session that makes branch intent explicit to callers."""
    return fork_session(workspace, parent_session_id, head_id=head_id)


def navigate_session_head(workspace: Path, session_id: str, head_id: str) -> dict[str, Any]:
    """Move the active view to a retained turn-tree head without deleting siblings."""
    record = _session_store(workspace.resolve()).set_active_head(session_id, head_id)
    return {
        "session_id": record.session_id,
        "active_head_id": record.active_head_id,
        "message_count": len(record.messages),
    }


def list_approvals(workspace: Path, *, status: str | None = "pending") -> list[dict[str, Any]]:
    """按状态列出 workspace 下的工具审批记录。"""
    return [approval.to_dict() for approval in _approval_store(workspace.resolve()).list(status=status)]


def list_checkpoints(workspace: Path, *, session_id: str | None = None) -> list[dict[str, Any]]:
    """列出 workspace 下可用于 rewind 的检查点记录。"""
    return [checkpoint.to_dict() for checkpoint in _checkpoint_store(workspace.resolve()).list(session_id=session_id)]


def list_timeline(workspace: Path, *, session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """读取指定会话或 workspace 最近的运行事件。"""
    return _timeline_store(workspace.resolve()).list(session_id=session_id, limit=limit)


def list_capabilities(workspace: Path, *, kind: CapabilityKind | None = None) -> list[dict[str, Any]]:
    """列出当前 workspace 可展示或可调用的能力清单。"""
    catalog = create_capability_catalog(workspace.resolve())
    return [descriptor.to_dict() for descriptor in catalog.list(kind=kind)]


def get_capability(workspace: Path, *, kind: CapabilityKind, name: str) -> dict[str, Any]:
    """按能力类型和名称读取单个能力描述。"""
    catalog = create_capability_catalog(workspace.resolve())
    return catalog.get(kind, name).to_dict()


def get_config(workspace: Path) -> dict[str, Any]:
    """读取 workspace 合并项目配置和运行时覆盖后的配置快照。"""
    return get_config_manager(workspace.resolve()).get_snapshot().to_dict()


def list_model_providers() -> list[dict[str, object]]:
    """返回 CodeMuse 当前支持的模型 Provider 列表。"""
    return list_llm_providers()


def list_provider_readiness(workspace: Path) -> list[dict[str, object]]:
    """检查当前 workspace 配置下各模型 Provider 的就绪状态。"""
    config = get_config_manager(workspace.resolve()).get_effective_config().model
    return provider_readiness(config)


def configure_model_provider(
    workspace: Path,
    provider: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Select a provider and persist its complete model configuration in user config.

    ``api_key_env`` is the *name* of an environment variable.  API key values are
    deliberately not accepted or written to the project configuration.
    """

    provider_name = _required_provider_name(provider)
    descriptor = get_provider_descriptor(provider_name)
    model_config = {
        "provider": descriptor.name,
        "model": _resolved_model_text(model, descriptor.default_model, "model"),
        "base_url": _resolved_model_text(base_url, descriptor.default_base_url, "base_url"),
        "api_key_env": _resolved_api_key_env(api_key_env, descriptor.default_api_key_env),
        # Null values are intentional JSON Merge Patch deletions.  They remove
        # limits from the previous provider so a provider change cannot inherit
        # stale generation settings.
        "temperature": _resolved_generation_option(
            temperature,
            getattr(descriptor, "default_temperature", None),
        ),
        "max_tokens": _resolved_generation_option(
            max_tokens,
            getattr(descriptor, "default_max_tokens", None),
        ),
    }
    return get_config_manager(workspace.resolve()).set_user_model_config(model_config).to_dict()


def refresh_memory(workspace: Path, *, max_files: int = 300) -> dict[str, Any]:
    """为 workspace 构建或刷新本地 memory/RAG 索引。"""
    return refresh_memory_index(workspace.resolve(), max_files=max_files).to_dict()


def search_memory(workspace: Path, query: str, *, limit: int = 6) -> dict[str, Any]:
    """搜索项目记忆、蓝图记忆和已索引的 workspace 文件。"""
    result = search_memory_pipeline(workspace.resolve(), query, limit=limit)
    payload = result.to_dict()
    payload["markdown"] = format_memory_pipeline_search(result)
    return payload


def list_mcp_resources(workspace: Path) -> list[dict[str, Any]]:
    """Discover resources exposed by configured MCP servers."""
    return [item.to_dict() for item in MCPManager.from_workspace(workspace).discover_resources()]


def read_mcp_resource(workspace: Path, server_name: str, uri: str) -> dict[str, Any]:
    """Read one configured MCP resource."""
    return MCPManager.from_workspace(workspace).read_resource(server_name, uri).__dict__


def list_mcp_prompts(workspace: Path) -> list[dict[str, Any]]:
    """Discover prompts exposed by configured MCP servers."""
    return [item.to_dict() for item in MCPManager.from_workspace(workspace).discover_prompts()]


def get_mcp_prompt(workspace: Path, server_name: str, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Materialize one MCP prompt using explicit arguments."""
    return MCPManager.from_workspace(workspace).get_prompt(server_name, name, arguments).__dict__


def list_learning_candidates(workspace: Path, *, status: str | None = None) -> list[dict[str, Any]]:
    """List reviewable durable-learning suggestions."""
    return [item.to_dict() for item in LearningRuntime(workspace).store.list(status=status)]


def approve_learning_candidate(workspace: Path, candidate_id: str) -> dict[str, Any]:
    """Promote one reviewed candidate into project memory."""
    return LearningRuntime(workspace).approve(candidate_id).to_dict()


def reject_learning_candidate(workspace: Path, candidate_id: str) -> dict[str, Any]:
    """Reject a learning candidate without changing project memory."""
    return LearningRuntime(workspace).reject(candidate_id).to_dict()


def set_config_path(workspace: Path, path: str, value: Any) -> dict[str, Any]:
    """通过 ConfigManager 把点路径配置写入项目配置，并返回新快照。"""
    return get_config_manager(workspace.resolve()).set_path(path, value).to_dict()


def patch_config(workspace: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a validated object into the project configuration."""
    return get_config_manager(workspace.resolve()).patch_project_config(patch).to_dict()


def set_runtime_config_path(workspace: Path, path: str, value: Any) -> dict[str, Any]:
    """把点路径配置写入进程内 runtime override，不落盘到项目配置。"""
    return get_config_manager(workspace.resolve()).set_runtime_override(path, value).to_dict()


def clear_runtime_config(workspace: Path) -> dict[str, Any]:
    """Clear process-local configuration overrides for a workspace."""
    return get_config_manager(workspace.resolve()).clear_runtime_overrides().to_dict()


def get_session_config(workspace: Path, session_id: str) -> dict[str, Any]:
    """Read persisted overrides for one session."""
    return SessionConfigStore(workspace).load(session_id)


def set_session_config_path(workspace: Path, session_id: str, path: str, value: Any) -> dict[str, Any]:
    """Validate and persist one session-scoped configuration path."""
    store = SessionConfigStore(workspace)
    previous = store.load(session_id)
    updated = store.set_path(session_id, path, value)
    config_patch = store.config_patch(session_id)
    try:
        CodeMuseConfig.from_dict(merge_patch(get_config_manager(workspace).get_effective_config().to_dict(), config_patch))
    except Exception:
        store.save(session_id, previous)
        raise
    return updated


def clear_session_config(workspace: Path, session_id: str) -> dict[str, Any]:
    """Remove all persisted overrides for one session."""
    SessionConfigStore(workspace).clear(session_id)
    return {}


def _required_provider_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("provider must be a string.")
    name = value.strip().lower()
    if not name:
        raise ValueError("provider is required.")
    return name


def _resolved_model_text(value: str | None, default: str, field: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    return value.strip() or default


def _resolved_api_key_env(value: str | None, default: str) -> str:
    selected = _resolved_model_text(value, default, "api_key_env")
    if selected and not _ENVIRONMENT_VARIABLE_NAME.fullmatch(selected):
        raise ValueError(
            "api_key_env must be an environment variable name; do not provide a raw API key."
        )
    return selected


def _resolved_generation_option(value: float | int | None, default: float | int | None) -> float | int | None:
    return default if value is None else value


def _merge_subscribers(
    *,
    subscriber: Subscriber | None,
    subscribers: list[Subscriber] | None,
) -> list[Subscriber]:
    """合并单个订阅回调和订阅回调列表，供 Runtime 统一注册。"""
    merged: list[Subscriber] = []
    if subscriber is not None:
        merged.append(subscriber)
    if subscribers:
        merged.extend(subscribers)
    return merged


def _assistant_preview(runtime: AgentRuntime, limit: int = 500) -> str:
    """从会话消息中提取最近一条 assistant 文本预览。"""
    for message in reversed(runtime.state.messages):
        if message.role != "assistant":
            continue
        text = message.text_content().strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."
    return ""


def _result_payload(runtime: AgentRuntime, events: list[AgentEvent], *, collect_events: bool) -> dict[str, Any]:
    """把 Runtime 状态和本轮事件整理成 SDK 返回结构。"""
    payload: dict[str, Any] = {
        "session_id": runtime.session_id,
        "assistant": _assistant_preview(runtime),
        "event_count": len(events),
        "state": runtime.state.to_dict(),
    }
    if collect_events:
        payload["events"] = [event.to_dict() for event in events]
    return payload


def _data_root(workspace: Path) -> Path:
    """计算 workspace 内 CodeMuse 本地数据根目录。"""
    return workspace.resolve() / ".data" / "codemuse"


def _session_store(workspace: Path) -> SessionStore:
    """创建指向当前 workspace 的会话存储对象。"""
    return SessionStore(_data_root(workspace) / "sessions")


def _approval_store(workspace: Path) -> PendingApprovalStore:
    """创建指向当前 workspace 的审批存储对象。"""
    return PendingApprovalStore(_data_root(workspace) / "approvals")


def _checkpoint_store(workspace: Path) -> CheckpointStore:
    """创建指向当前 workspace 的检查点存储对象。"""
    return CheckpointStore(_data_root(workspace) / "checkpoints")


def _timeline_store(workspace: Path) -> TimelineStore:
    """创建指向当前 workspace 的 timeline 事件存储对象。"""
    return TimelineStore(_data_root(workspace) / "timeline")
