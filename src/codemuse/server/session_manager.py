"""管理 Web/HTTP 场景下的会话实例、任务队列和事件缓存。"""
from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.app.bootstrap import build_agent
from codemuse.runtime.events import AgentEvent
from codemuse.runtime.session_host import SessionHost
from codemuse.runtime.runtime import AgentRuntime
from codemuse.storage.sessions import SessionRecord, SessionStore, build_session_tree


@dataclass(frozen=True)
class SessionJob:
    # Web 请求先变成 job，再由单个 worker 顺序执行，避免多个请求同时修改 Runtime 状态。
    """后台会话队列中的一项待执行任务。"""
    job_id: str
    action: str
    payload: dict[str, Any]


class SessionHandle:
    """封装单个 Web 会话的 Runtime、任务队列和事件缓存。"""
    def __init__(self, runtime: AgentRuntime) -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        self.runtime = runtime
        self.session_id = runtime.session_id
        self._jobs: queue.Queue[SessionJob | None] = queue.Queue()
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._next_event_id = 1
        self._closed = False
        # 每个会话只有一个 worker：prompt / approve / checkpoint / rewind 都按进入队列的顺序运行。
        self._worker = threading.Thread(target=self._run_worker, name=f"codemuse-session-{self.session_id}", daemon=True)
        self.runtime.subscribe(self._record_runtime_event)
        self._restore_message_events()
        self._worker.start()

    def prompt(self, text: str) -> str:
        """接收用户输入并驱动 Agent 执行一轮任务。"""
        clean = text.strip()
        if not clean:
            raise ValueError("Prompt cannot be empty.")
        return self._queue_job("prompt", {"text": clean})

    def enqueue_message(self, text: str, *, delivery: str = "follow_up") -> str:
        """Queue steering input behind the session worker."""
        clean = text.strip()
        if not clean:
            raise ValueError("Queued message cannot be empty.")
        return self._queue_job("enqueue", {"text": clean, "delivery": delivery})

    def compact(self) -> str:
        """Queue a persisted conversation compaction operation."""
        return self._queue_job("compact", {})

    def approve(self, approval_id: str) -> str:
        """批准一个等待中的工具调用，并让 Runtime 继续执行。"""
        return self._queue_job("approve", {"approval_id": approval_id})

    def reject(self, approval_id: str) -> str:
        """拒绝一个等待中的工具调用，并写回会话。"""
        return self._queue_job("reject", {"approval_id": approval_id})

    def checkpoint(self, label: str = "manual checkpoint") -> str:
        """将 checkpoint 任务投递到当前 session 的后台队列。"""
        return self._queue_job("checkpoint", {"label": label or "manual checkpoint"})

    def rewind(self, checkpoint_id: str, *, mode: str = "conversation_and_workspace") -> str:
        """将当前会话恢复到指定检查点。"""
        return self._queue_job("rewind", {"checkpoint_id": checkpoint_id, "mode": mode})

    def preview_rewind(self, checkpoint_id: str, *, mode: str = "conversation_and_workspace") -> dict[str, Any]:
        return self.runtime.preview_rewind(checkpoint_id, mode=mode)

    def cancel(self) -> dict[str, Any]:
        """请求中断正在运行的任务，并清空尚未启动的队列任务。"""
        drained = 0
        while True:
            try:
                pending = self._jobs.get_nowait()
            except queue.Empty:
                break
            if pending is None:
                # 重新放回关闭信号，避免 worker 永远挂起。
                self._jobs.put(None)
                break
            drained += 1
            self._record_backend_event(
                f"{pending.action}_cancelled",
                message=f"{pending.action} cancelled before start.",
                details={"job_id": pending.job_id},
            )
        self.runtime.request_cancel()
        self._record_backend_event(
            "cancel_requested",
            message="Cancel requested.",
            details={"drained_jobs": drained},
        )
        return {"drained_jobs": drained}

    def list_approvals(self, *, status: str | None = "pending") -> list[dict[str, Any]]:
        """列出当前会话自己的审批项，避免旧会话审批泄漏到当前 UI。"""
        if self.runtime.approval_store is None:
            return []
        return [
            approval.to_dict()
            for approval in self.runtime.approval_store.list(status=status)
            if approval.session_id == self.session_id
        ]

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """列出当前会话可回退的检查点。"""
        if self.runtime.checkpoint_store is None:
            return []
        return [checkpoint.to_dict() for checkpoint in self.runtime.checkpoint_store.list(session_id=self.session_id)]

    def events_after(self, cursor: int = 0) -> dict[str, Any]:
        """按事件游标返回 session 中尚未被前端拉取的事件。"""
        with self._lock:
            events = [event for event in self._events if int(event["event_id"]) > cursor]
            next_cursor = int(self._events[-1]["event_id"]) if self._events else cursor
        return {"events": events, "next_cursor": next_cursor}

    def snapshot(self) -> dict[str, Any]:
        """生成当前 session 的状态摘要，包括会话 id、阶段和最新事件游标。"""
        with self._lock:
            pending_jobs = self._jobs.qsize()
        return {
            "session_id": self.session_id,
            "parent_session_id": self.runtime.session.parent_session_id,
            "root_session_id": self.runtime.session.root_session_id,
            "depth": self.runtime.session.depth,
            "forked_at_message": self.runtime.session.forked_at_message,
            "active_head_id": self.runtime.session.active_head_id,
            "turns": list(self.runtime.session.turns),
            "pending_jobs": pending_jobs,
            "state": self.runtime.state.to_dict(),
        }

    def close(self) -> None:
        """释放该对象持有的工作线程、会话或连接资源。"""
        self._closed = True
        self._jobs.put(None)

    def _run_worker(self) -> None:
        """按队列顺序执行 prompt、审批、checkpoint 和 rewind 任务。"""
        while True:
            job = self._jobs.get()
            if job is None:
                self._record_backend_event("session_closed", message="Session worker stopped.")
                return
            self._record_backend_event(f"{job.action}_started", message=f"{job.action} started.", details={"job_id": job.job_id})
            try:
                self._run_job(job)
                self._record_backend_event(f"{job.action}_completed", message=f"{job.action} completed.", details={"job_id": job.job_id})
            except Exception as exc:  # noqa: BLE001 - backend records failures as events
                self._record_backend_event(
                    f"{job.action}_failed",
                    message=str(exc),
                    details={"job_id": job.job_id},
                    is_error=True,
                )

    def _queue_job(self, action: str, payload: dict[str, Any]) -> str:
        """创建任务编号、记录排队事件，并把任务放入后台队列。"""
        if self._closed:
            raise RuntimeError(f"Session is closed: {self.session_id}")
        job = SessionJob(job_id=str(uuid.uuid4()), action=action, payload=payload)
        self._record_backend_event(f"{action}_queued", message=f"{action} queued.", details={"job_id": job.job_id})
        self._jobs.put(job)
        return job.job_id

    def _run_job(self, job: SessionJob) -> None:
        """把 SessionJob 分发到 Runtime 对应的方法。"""
        if job.action == "prompt":
            self.runtime.prompt(str(job.payload["text"]))
            return
        if job.action == "enqueue":
            self.runtime.enqueue_message(str(job.payload["text"]), delivery=str(job.payload.get("delivery") or "follow_up"))
            return
        if job.action == "compact":
            self.runtime.compact()
            return
        if job.action == "approve":
            self.runtime.approve(str(job.payload["approval_id"]))
            return
        if job.action == "reject":
            self.runtime.reject(str(job.payload["approval_id"]))
            return
        if job.action == "checkpoint":
            self.runtime.create_checkpoint(str(job.payload.get("label") or "manual checkpoint"))
            return
        if job.action == "rewind":
            self.runtime.rewind(str(job.payload["checkpoint_id"]), mode=str(job.payload.get("mode") or "conversation_and_workspace"))
            return
        raise ValueError(f"Unknown session job action: {job.action}")

    def _record_runtime_event(self, event: AgentEvent) -> None:
        """记录运行过程中的事件或状态变化。"""
        payload = event.to_dict()
        self._append_event(payload)

    def _record_backend_event(
        self,
        event_type: str,
        *,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        is_error: bool = False,
    ) -> None:
        """记录运行过程中的事件或状态变化。"""
        event = AgentEvent(
            type=event_type,
            session_id=self.session_id,
            turn_id=self.runtime.state.turn_id,
            phase=self.runtime.state.phase,
            message=message,
            details=details or {},
            is_error=is_error,
        )
        self._append_event(event.to_dict())

    def _restore_message_events(self) -> None:
        """Restore persisted conversation messages for the initial Web view.

        Tool messages remain in ``runtime.state.messages`` so a restored runtime
        retains the protocol context required for later provider requests. They
        are deliberately not replayed as live ``tool_result`` events: those
        events describe work completed before this handle was opened, not work
        currently executing in the Web session.
        """
        for message in self.runtime.state.messages:
            text = message.text_content()
            if message.role == "user" and text.strip():
                self._append_event(
                    AgentEvent(
                        type="local_user_prompt",
                        session_id=self.session_id,
                        turn_id=self.runtime.state.turn_id,
                        phase="saved",
                        message=text,
                        timestamp=message.timestamp,
                    ).to_dict()
                )
                continue
            if message.role == "assistant" and text.strip():
                self._append_event(
                    AgentEvent(
                        type="message",
                        session_id=self.session_id,
                        turn_id=self.runtime.state.turn_id,
                        phase="saved",
                        message=text,
                        timestamp=message.timestamp,
                    ).to_dict()
                )
                continue

    def _append_event(self, payload: dict[str, Any]) -> None:
        """给事件分配递增游标并保存到当前会话的内存缓存。"""
        with self._condition:
            payload["event_id"] = self._next_event_id
            self._next_event_id += 1
            self._events.append(payload)
            if len(self._events) > 500:
                self._events = self._events[-500:]
            self._condition.notify_all()


class WebSessionManager:
    """管理 HTTP/Web 场景下的多个 SessionHandle。"""
    def __init__(self, *, default_workspace: Path) -> None:
        """记录默认工作区，并初始化会话句柄表。"""
        self.default_workspace = default_workspace.resolve()
        self.session_host = SessionHost()
        self._handles: dict[str, SessionHandle] = {}
        self._lock = threading.Lock()

    def set_default_workspace(self, workspace: Path) -> Path:
        """切换 Web 端后续新会话和全局 API 使用的默认工作区。"""
        resolved = workspace.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Workspace does not exist: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Workspace is not a directory: {resolved}")
        with self._lock:
            if resolved == self.default_workspace:
                return self.default_workspace
            handles = list(self._handles.values())
            self._handles = {}
            self.default_workspace = resolved
        for handle in handles:
            handle.close()
        return resolved

    def create_session(self, *, workspace: Path | None = None, parent_session_id: str | None = None, head_id: str | None = None) -> SessionHandle:
        """为指定 workspace 构建 AgentRuntime，并用 SessionHandle 管理它。"""
        resolved_workspace = (workspace or self.default_workspace).resolve()
        if parent_session_id:
            with self._lock:
                parent_handle = self._handles.get(parent_session_id)
            if parent_handle is not None:
                parent_snapshot = parent_handle.snapshot()
                if parent_snapshot["pending_jobs"] or parent_snapshot["state"]["is_running"]:
                    raise ValueError("Cannot fork a session while it is running or has queued jobs.")
            fork = self.session_host.fork_session(resolved_workspace, parent_session_id, head_id=head_id)
            runtime = self.session_host.restore_session(resolved_workspace, fork.session_id)
        else:
            runtime = self.session_host.create_session(resolved_workspace)
        handle = SessionHandle(runtime)
        with self._lock:
            self._handles[handle.session_id] = handle
        return handle

    def get_session(self, session_id: str) -> SessionHandle:
        """获取已加载会话；不存在时从本地 SessionStore 恢复。"""
        with self._lock:
            handle = self._handles.get(session_id)
        if handle is None:
            # HTTP 客户端只知道 session_id；真正的 Agent 状态仍由 Runtime 和本地 SessionStore 恢复。
            runtime = self.session_host.restore_session(self.default_workspace, session_id)
            handle = SessionHandle(runtime)
            with self._lock:
                self._handles[session_id] = handle
        return handle

    def list_sessions(self) -> list[dict[str, Any]]:
        """合并当前进程会话和本地持久化会话，供前端重启后展示历史记录。"""
        with self._lock:
            handles = list(self._handles.values())
        snapshots = {handle.session_id: handle.snapshot() for handle in handles}
        store = SessionStore(self.default_workspace / ".data" / "codemuse" / "sessions")
        for record in store.list():
            if record.session_id in snapshots:
                snapshots[record.session_id]["created_at"] = record.created_at
                snapshots[record.session_id]["updated_at"] = record.updated_at
                snapshots[record.session_id]["message_count"] = len(record.messages)
                snapshots[record.session_id].update(_lineage_payload(record))
                continue
            snapshots[record.session_id] = {
                "session_id": record.session_id,
                "pending_jobs": 0,
                "state": {
                    "session_id": record.session_id,
                    "turn_id": 0,
                    "phase": "saved",
                    "is_running": False,
                    "error_message": None,
                    "pending_tool_calls": [],
                    "queued_messages": [],
                    "memory_context": {},
                },
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "message_count": len(record.messages),
                **_lineage_payload(record),
            }
        return sorted(snapshots.values(), key=lambda item: float(item.get("updated_at") or 0), reverse=True)

    def list_session_tree(self, sessions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """把会话列表嵌套成树，同时保留损坏关系或孤儿节点。"""
        return build_session_tree(sessions if sessions is not None else self.list_sessions())


def _lineage_payload(record: SessionRecord) -> dict[str, Any]:
    return {
        "parent_session_id": record.parent_session_id,
        "root_session_id": record.root_session_id,
        "depth": record.depth,
        "forked_at_message": record.forked_at_message,
        "active_head_id": record.active_head_id,
        "turns": list(record.turns),
    }
