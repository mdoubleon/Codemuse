"""持久化等待用户批准或拒绝的工具调用。"""
from __future__ import annotations

import json
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
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
        )


class PendingApprovalStore:
    """把待审批工具调用保存到本地 JSON，方便 CLI/Web 后续批准或拒绝。"""

    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

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
        approval.updated_at = time.time()
        path = self._path(approval.approval_id)
        path.write_text(json.dumps(approval.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, approval_id: str) -> PendingApproval:
        """按标识读取本地存储中的对象。"""
        path = self._path(approval_id)
        if not path.exists():
            raise FileNotFoundError(f"Approval not found: {approval_id}")
        return PendingApproval.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, *, status: str | None = None) -> list[PendingApproval]:
        """列出当前存储或目录中的对象。"""
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
        approval = self.load(approval_id)
        approval.status = status
        if details_update:
            approval.details.update(details_update)
        self.save(approval)
        return approval

    def _path(self, approval_id: str) -> Path:
        """根据标识计算本地存储路径。"""
        return self.root / f"{approval_id}.json"
