"""Session lifecycle facade shared by non-HTTP entry points."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from codemuse.app.bootstrap import DEFAULT_SYSTEM_PROMPT, build_agent
from codemuse.runtime.events import AgentEvent
from codemuse.runtime.lifecycle import SESSION_COMPACTED, SESSION_FORKED, SESSION_RESTORE, SESSION_START
from codemuse.runtime.runtime import AgentRuntime
from codemuse.storage.sessions import SessionRecord, SessionStore

LifecycleSubscriber = Callable[[AgentEvent], None]


@dataclass
class ForkResult:
    source_session_id: str
    session_id: str
    source_head_id: str | None = None
    active_head_id: str | None = None


@dataclass
class SessionTreeView:
    entries: list[dict[str, Any]]
    session_id: str | None = None


class SessionHost:
    def __init__(self, *, runtime_factory: Callable[..., AgentRuntime] | None = None, session_store_factory: Callable[[Path], SessionStore] | None = None, **_: Any) -> None:
        self._runtime_factory = runtime_factory or (lambda workspace, session_id=None: build_agent(workspace, session_id=session_id))
        self._session_store_factory = session_store_factory or (lambda root: SessionStore(root))

    def _store(self, workspace: Path) -> SessionStore:
        return self._session_store_factory(workspace.resolve() / ".data" / "codemuse" / "sessions")

    def _runtime(self, workspace: Path, session_id: str | None = None) -> AgentRuntime:
        try:
            return self._runtime_factory(workspace, session_id=session_id)
        except TypeError:
            record = self._store(workspace).load(session_id) if session_id else self._store(workspace).create(DEFAULT_SYSTEM_PROMPT)
            return self._runtime_factory(workspace, record, None)

    def _emit(self, runtime: AgentRuntime, event_type: str, subscribers: list[LifecycleSubscriber] | None, details: dict[str, Any] | None = None) -> None:
        event = AgentEvent(type=event_type, session_id=runtime.session_id, phase=runtime.state.phase, turn_id=runtime.state.turn_id, details=details or {})
        for subscriber in subscribers or []: subscriber(event)

    def create_session(self, workspace: Path, *, lifecycle_subscribers: list[LifecycleSubscriber] | None = None) -> AgentRuntime:
        runtime = self._runtime(workspace)
        for subscriber in lifecycle_subscribers or []: runtime.subscribe(subscriber)
        self._emit(runtime, SESSION_START, lifecycle_subscribers, {"new_session": True})
        return runtime

    def restore_session(self, workspace: Path, session_id: str, *, lifecycle_subscribers: list[LifecycleSubscriber] | None = None) -> AgentRuntime:
        runtime = self._runtime(workspace, session_id)
        for subscriber in lifecycle_subscribers or []: runtime.subscribe(subscriber)
        self._emit(runtime, SESSION_RESTORE, lifecycle_subscribers, {"restored": True})
        return runtime

    def fork_session(self, workspace: Path, session_id: str, *, head_id: str | None = None, lifecycle_subscribers: list[LifecycleSubscriber] | None = None, **_: Any) -> ForkResult:
        store = self._store(workspace)
        child = store.fork_from_head(session_id, head_id) if head_id else store.fork(session_id)
        store.save(child)
        event = AgentEvent(type=SESSION_FORKED, session_id=child.session_id, details={"source_session_id": session_id})
        for subscriber in lifecycle_subscribers or []: subscriber(event)
        return ForkResult(source_session_id=session_id, session_id=child.session_id)

    def navigate_tree(self, workspace: Path, session_id: str, target_head_id: str, *, lifecycle_subscribers: list[LifecycleSubscriber] | None = None) -> dict[str, Any]:
        record = self._store(workspace).set_active_head(session_id, target_head_id)
        event = AgentEvent(type="session_tree_navigated", session_id=session_id, details={"active_head_id": record.active_head_id})
        for subscriber in lifecycle_subscribers or []: subscriber(event)
        return {"session_id": session_id, "active_head_id": record.active_head_id}

    def list_sessions(self, workspace: Path) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self._store(workspace).list()]

    def switch_session(self, workspace: Path, current_session_id: str, target_session_id: str, *, lifecycle_subscribers: list[LifecycleSubscriber] | None = None, **_: Any) -> AgentRuntime:
        runtime = self.restore_session(workspace, target_session_id, lifecycle_subscribers=lifecycle_subscribers)
        self._emit(runtime, "session_switched", lifecycle_subscribers, {"from_session_id": current_session_id, "to_session_id": target_session_id})
        return runtime

    def create_checkpoint(self, workspace: Path, *, session_id: str, label: str = "manual checkpoint", lifecycle_subscribers: list[LifecycleSubscriber] | None = None, **_: Any) -> Any:
        runtime = self.restore_session(workspace, session_id, lifecycle_subscribers=lifecycle_subscribers)
        return runtime.create_checkpoint(label)

    def list_checkpoints(self, workspace: Path, *, session_id: str | None = None) -> list[dict[str, Any]]:
        from codemuse.storage.checkpoints import CheckpointStore
        return [item.to_dict() for item in CheckpointStore(workspace.resolve() / ".data" / "codemuse" / "checkpoints").list(session_id=session_id)]

    def get_tree(self, workspace: Path, session_id: str | None = None, **_: Any) -> SessionTreeView:
        return SessionTreeView(entries=self._store(workspace).list_tree(), session_id=session_id)

    def compact_session(self, runtime: AgentRuntime, *, subscribers: list[LifecycleSubscriber] | None = None) -> dict[str, Any]:
        result = runtime.compact()
        event = AgentEvent(type=SESSION_COMPACTED, session_id=runtime.session_id, details=result)
        for subscriber in subscribers or []: subscriber(event)
        return result
