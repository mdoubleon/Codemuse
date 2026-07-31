"""持久化等待用户批准或拒绝的工具调用。"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.domain.tools import ToolCall


@dataclass
class PendingApproval:
    """保存一次等待用户批准的工具调用，包括参数、原因和执行前预览。"""
    approval_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    execution_status: str = "pending"
    execution_id: str | None = None
    execution_started_at: float | None = None
    execution_finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """把 PendingApproval 转成可写入文件或 API 响应的字典。"""
        return {
            "approval_id": self.approval_id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "reason": self.reason,
            "details": self.details,
            "status": self.status,
            "execution_status": self.execution_status,
            "execution_id": self.execution_id,
            "execution_started_at": self.execution_started_at,
            "execution_finished_at": self.execution_finished_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PendingApproval":
        """把字典里的字段校正并恢复成 PendingApproval 对象。"""
        return cls(
            approval_id=str(payload["approval_id"]),
            session_id=str(payload["session_id"]),
            tool_call_id=str(payload["tool_call_id"]),
            tool_name=str(payload["tool_name"]),
            arguments=dict(payload.get("arguments") or {}),
            reason=str(payload.get("reason") or ""),
            details=dict(payload.get("details") or {}),
            status=str(payload.get("status") or "pending"),
            execution_status=str(payload.get("execution_status") or _legacy_execution_status(payload)),
            execution_id=str(payload["execution_id"]) if payload.get("execution_id") else None,
            execution_started_at=float(payload["execution_started_at"]) if payload.get("execution_started_at") is not None else None,
            execution_finished_at=float(payload["execution_finished_at"]) if payload.get("execution_finished_at") is not None else None,
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
        )


class PendingApprovalStore:
    """把待审批工具调用保存到本地 JSON，方便 CLI/Web 后续批准或拒绝。"""

    _locks_guard = threading.Lock()
    _root_locks: dict[Path, threading.RLock] = {}

    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locks_guard:
            self._lock = self._root_locks.setdefault(self.root, threading.RLock())

    def create(self, *, session_id: str, call: ToolCall, reason: str, details: dict[str, Any] | None = None) -> PendingApproval:
        """把等待审批的工具调用落盘，供 CLI/Web 后续批准或拒绝。"""
        approval = PendingApproval(
            approval_id=str(uuid.uuid4()),
            session_id=session_id,
            tool_call_id=call.id,
            tool_name=call.name,
            arguments=dict(call.arguments),
            reason=reason,
            details=details or {},
        )
        self.save(approval)
        return approval

    def save(self, approval: PendingApproval) -> None:
        """将对象写入本地存储。"""
        with self._lock:
            self._save_unlocked(approval)

    def load(self, approval_id: str) -> PendingApproval:
        """按标识读取本地存储中的对象。"""
        with self._lock:
            return self._load_unlocked(approval_id)

    def list(self, *, status: str | None = None) -> list[PendingApproval]:
        """列出当前存储或目录中的对象。"""
        with self._lock:
            approvals: list[PendingApproval] = []
            for path in sorted(self.root.glob("*.json")):
                try:
                    approval = PendingApproval.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                if status is None or approval.status == status:
                    approvals.append(approval)
            return sorted(approvals, key=lambda item: item.updated_at, reverse=True)

    def mark(self, approval_id: str, status: str, details_update: dict[str, Any] | None = None) -> PendingApproval:
        """把指定 approval 的状态改为 approved/rejected/stale，并可追加状态原因。"""
        with self._lock:
            approval = self._load_unlocked(approval_id)
            approval.status = status
            if status in {"rejected", "stale", "invalid"} and approval.execution_status == "pending":
                approval.execution_status = "cancelled"
                approval.execution_finished_at = time.time()
            if details_update:
                approval.details.update(details_update)
            self._save_unlocked(approval)
            return approval

    def begin_execution(self, approval_id: str, *, execution_id: str | None = None) -> PendingApproval:
        """Atomically claim a pending approval before running its side effect."""
        with self._lock:
            approval = self._load_unlocked(approval_id)
            if approval.execution_status == "completed":
                return approval
            if approval.execution_status == "executing":
                raise RuntimeError(
                    f"Approval execution is already in progress: {approval_id} "
                    f"(execution_id={approval.execution_id})"
                )
            if approval.execution_status == "failed":
                raise RuntimeError(
                    f"Approval execution previously failed and will not be retried: {approval_id} "
                    f"(execution_id={approval.execution_id})"
                )
            if approval.status != "pending" or approval.execution_status != "pending":
                raise ValueError(f"Approval is not executable: {approval_id} ({approval.status})")
            now = time.time()
            approval.status = "approved"
            approval.execution_status = "executing"
            approval.execution_id = execution_id or str(uuid.uuid4())
            approval.execution_started_at = now
            approval.execution_finished_at = None
            self._save_unlocked(approval)
            return approval

    def complete_execution(
        self,
        approval_id: str,
        *,
        execution_id: str,
        result: dict[str, Any],
    ) -> PendingApproval:
        """Persist a completed result so recovery never needs to rerun the tool."""
        with self._lock:
            approval = self._load_unlocked(approval_id)
            self._assert_execution_owner(approval, execution_id)
            approval.status = "approved"
            approval.execution_status = "completed"
            approval.execution_finished_at = time.time()
            approval.details["execution_result"] = result
            self._save_unlocked(approval)
            return approval

    def fail_execution(
        self,
        approval_id: str,
        *,
        execution_id: str,
        error: str,
    ) -> PendingApproval:
        """Record a terminal failure and refuse ambiguous automatic retries."""
        with self._lock:
            approval = self._load_unlocked(approval_id)
            self._assert_execution_owner(approval, execution_id)
            approval.status = "approved"
            approval.execution_status = "failed"
            approval.execution_finished_at = time.time()
            approval.details["execution_error"] = error
            self._save_unlocked(approval)
            return approval

    def cancel_execution(
        self,
        approval_id: str,
        *,
        execution_id: str,
        status: str,
        details_update: dict[str, Any] | None = None,
    ) -> PendingApproval:
        """Cancel a claimed execution before its side effect begins."""
        if status not in {"stale", "invalid"}:
            raise ValueError(f"Unsupported cancelled execution status: {status}")
        with self._lock:
            approval = self._load_unlocked(approval_id)
            self._assert_execution_owner(approval, execution_id)
            approval.status = status
            approval.execution_status = "cancelled"
            approval.execution_finished_at = time.time()
            if details_update:
                approval.details.update(details_update)
            self._save_unlocked(approval)
            return approval

    def reconcile_for_rewind(
        self,
        *,
        session_id: str,
        checkpoint_id: str,
        checkpoint_created_at: float,
        checkpoint_approvals: dict[str, dict[str, Any]] | None = None,
        approval_ids: set[str] | None = None,
    ) -> dict[str, list[str]]:
        """Invalidate approval state created or changed after a conversation checkpoint.

        A rewind must not leave a later exact-effect approval executable against
        restored conversation state. Executions that are still in progress are
        intentionally reported as blockers instead of being silently forgotten.
        """
        snapshots = checkpoint_approvals or {}
        with self._lock:
            session_approvals = [
                PendingApproval.from_dict(json.loads(path.read_text(encoding="utf-8")))
                for path in sorted(self.root.glob("*.json"))
                if _approval_file_belongs_to_session(path, session_id)
            ]
            # All heads in one session share the same workspace. A side effect
            # still in flight on a sibling head can race with a workspace rewind,
            # so blockers deliberately use the whole session rather than the
            # branch-scoped invalidation set below.
            blockers = [
                approval.approval_id
                for approval in session_approvals
                if approval.execution_status == "executing"
            ]
            if blockers:
                return {"invalidated": [], "retained": [], "blockers": blockers}
            approvals = session_approvals
            if approval_ids is not None:
                approvals = [approval for approval in approvals if approval.approval_id in approval_ids]
            candidates = [
                approval
                for approval in approvals
                if _approval_changed_since_checkpoint(
                    approval,
                    checkpoint_created_at=checkpoint_created_at,
                    checkpoint_snapshot=snapshots.get(approval.approval_id),
                )
            ]
            invalidated: list[str] = []
            retained: list[str] = []
            for approval in approvals:
                if approval not in candidates:
                    retained.append(approval.approval_id)
                    continue
                approval.status = "stale"
                if approval.execution_status == "pending":
                    approval.execution_status = "cancelled"
                    approval.execution_finished_at = time.time()
                approval.details.update(
                    {
                        "rewound_from_checkpoint": checkpoint_id,
                        "rewind_checkpoint_created_at": checkpoint_created_at,
                        "stale_reason": "Approval was created or changed after the rewind checkpoint.",
                    }
                )
                self._save_unlocked(approval)
                invalidated.append(approval.approval_id)
            return {"invalidated": invalidated, "retained": retained, "blockers": []}

    def _load_unlocked(self, approval_id: str) -> PendingApproval:
        path = self._path(approval_id)
        if not path.exists():
            raise FileNotFoundError(f"Approval not found: {approval_id}")
        return PendingApproval.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _save_unlocked(self, approval: PendingApproval) -> None:
        approval.updated_at = time.time()
        path = self._path(approval.approval_id)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(approval.to_dict(), ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _assert_execution_owner(approval: PendingApproval, execution_id: str) -> None:
        if approval.execution_status != "executing" or approval.execution_id != execution_id:
            raise RuntimeError(
                f"Approval execution ownership changed: {approval.approval_id} "
                f"(expected={execution_id}, actual={approval.execution_id}, status={approval.execution_status})"
            )

    def _path(self, approval_id: str) -> Path:
        """根据标识计算本地存储路径。"""
        return self.root / f"{approval_id}.json"


def _legacy_execution_status(payload: dict[str, Any]) -> str:
    """Map pre-state-machine records without changing their public decision status."""
    status = str(payload.get("status") or "pending")
    if status == "approved":
        return "completed"
    if status in {"rejected", "stale", "invalid"}:
        return "cancelled"
    return "pending"


def _approval_file_belongs_to_session(path: Path, session_id: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and str(payload.get("session_id") or "") == session_id


def _approval_changed_since_checkpoint(
    approval: PendingApproval,
    *,
    checkpoint_created_at: float,
    checkpoint_snapshot: dict[str, Any] | None,
) -> bool:
    if checkpoint_snapshot is None:
        return approval.created_at > checkpoint_created_at
    return any(
        approval_value != checkpoint_snapshot.get(field)
        for field, approval_value in {
            "status": approval.status,
            "execution_status": approval.execution_status,
            "execution_id": approval.execution_id,
            "updated_at": approval.updated_at,
        }.items()
    )
