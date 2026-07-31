"""Execute validated plans and own the approval execution state machine."""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.domain.tools import ToolCall
from codemuse.runtime.planner import PlannedToolCall
from codemuse.storage.approvals import PendingApproval, PendingApprovalStore
from codemuse.tools.base import ToolResult
from codemuse.tools.effects import validate_effect_digest, validate_tool_effect_preview
from codemuse.tools.policy import ALLOW, DENY, ToolPolicyEvaluator
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.validation import ToolArgumentValidationError

BeforeExecute = Callable[[ToolCall, str], None]
TransformResult = Callable[[ToolCall, ToolResult], ToolResult]

_WORKSPACE_LOCKS_GUARD = threading.Lock()
_WORKSPACE_EXECUTION_LOCKS: dict[Path, threading.RLock] = {}


@dataclass(frozen=True)
class ExecutionOutcome:
    call: ToolCall
    result: ToolResult
    execution_id: str
    approval_id: str | None = None
    replayed: bool = False


class ApprovalValidationError(RuntimeError):
    """An approval no longer matches the exact call or target state."""

    def __init__(self, status: str, validation: dict[str, Any]) -> None:
        self.status = status
        self.validation = validation
        super().__init__(str(validation.get("reason") or f"Approval is {status}."))


class ToolExecutionError(RuntimeError):
    """A planned execution failed after it acquired an execution id."""

    def __init__(
        self,
        *,
        call: ToolCall,
        execution_id: str,
        approval_id: str | None,
        cause: Exception,
    ) -> None:
        self.call = call
        self.execution_id = execution_id
        self.approval_id = approval_id
        self.cause = cause
        super().__init__(str(cause))


class Executor:
    """Accept only Planner output and run tools behind the approval contract."""

    def __init__(
        self,
        *,
        workspace: Path,
        tool_registry: ToolRegistry,
        approval_store: PendingApprovalStore | None,
        policy_evaluator: ToolPolicyEvaluator | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self._execution_lock = _workspace_execution_lock(self.workspace)
        self.tool_registry = tool_registry
        self.approval_store = approval_store
        self.policy_evaluator = policy_evaluator or ToolPolicyEvaluator()

    def execute(
        self,
        planned: PlannedToolCall,
        *,
        before_execute: BeforeExecute | None = None,
        transform_result: TransformResult | None = None,
    ) -> ExecutionOutcome:
        """Execute an allowed call; denied or approval-bound calls are rejected."""
        if planned.action != ALLOW:
            raise PermissionError(
                f"Executor accepts only allowed calls; {planned.call.name} was planned as {planned.action}."
            )
        execution_id = str(uuid.uuid4())
        try:
            result = self._execute_call(
                planned.call,
                execution_id=execution_id,
                before_execute=before_execute,
                transform_result=transform_result,
            )
        except Exception as exc:  # noqa: BLE001 - normalize the execution boundary
            raise ToolExecutionError(
                call=planned.call,
                execution_id=execution_id,
                approval_id=None,
                cause=exc,
            ) from exc
        return ExecutionOutcome(call=planned.call, result=result, execution_id=execution_id)

    def execute_planned(
        self,
        planned: PlannedToolCall,
        *,
        before_execute: BeforeExecute | None = None,
        transform_result: TransformResult | None = None,
    ) -> ExecutionOutcome:
        """Explicitly named alias for the Planner -> Executor hand-off."""
        return self.execute(
            planned,
            before_execute=before_execute,
            transform_result=transform_result,
        )

    def execute_approved(
        self,
        approval_id: str,
        *,
        session_id: str,
        before_execute: BeforeExecute | None = None,
        transform_result: TransformResult | None = None,
    ) -> ExecutionOutcome:
        """Validate, claim, execute, and durably finish one exact-effect approval."""
        with self._execution_lock:
            return self._execute_approved_locked(
                approval_id,
                session_id=session_id,
                before_execute=before_execute,
                transform_result=transform_result,
            )

    def _execute_approved_locked(
        self,
        approval_id: str,
        *,
        session_id: str,
        before_execute: BeforeExecute | None = None,
        transform_result: TransformResult | None = None,
    ) -> ExecutionOutcome:
        """Run one approved effect while holding the workspace execution lock."""
        store = self._require_approval_store()
        approval = store.load(approval_id)
        if approval.session_id != session_id:
            raise ValueError(f"Approval belongs to another session: {approval.session_id}")
        call = ToolCall(
            id=approval.tool_call_id,
            name=approval.tool_name,
            arguments=dict(approval.arguments),
        )

        if approval.status in {"stale", "invalid"}:
            reason_key = "stale_reason" if approval.status == "stale" else "invalid_reason"
            raise ApprovalValidationError(
                approval.status,
                {
                    "ok": False,
                    "reason": str(approval.details.get(reason_key) or f"Approval is {approval.status}."),
                    "gate": "approval_status",
                    "checkpoint_id": approval.details.get("rewound_from_checkpoint"),
                },
            )

        if approval.execution_status == "completed":
            return ExecutionOutcome(
                call=call,
                result=self._stored_result(approval, call),
                execution_id=str(approval.execution_id or "legacy-completed"),
                approval_id=approval_id,
                replayed=True,
            )
        if approval.status != "pending":
            if approval.execution_status == "executing":
                raise RuntimeError(
                    f"Approval execution outcome is unresolved; refusing a duplicate run: {approval_id} "
                    f"(execution_id={approval.execution_id})"
                )
            if approval.execution_status == "failed":
                raise RuntimeError(
                    f"Approval execution failed and requires a new plan before retry: {approval_id} "
                    f"(execution_id={approval.execution_id})"
                )
            raise ValueError(f"Approval is not pending: {approval_id}")

        # Re-run the inexpensive gates at the trust boundary. A policy change or
        # a schema mutation after staging must not turn an old approval into a
        # newly permitted effect.
        try:
            spec = self.tool_registry.get_spec(approval.tool_name)
            self.tool_registry.validate_arguments(approval.tool_name, approval.arguments)
        except (KeyError, ValueError, ToolArgumentValidationError) as exc:
            validation = {"ok": False, "reason": str(exc), "gate": "argument_validation"}
            store.mark(approval_id, "invalid", details_update={"invalid_reason": str(exc), "invalid_gate": "argument_validation"})
            raise ApprovalValidationError("invalid", validation) from exc
        current_policy = self.policy_evaluator.evaluate(spec)
        if current_policy.action == DENY:
            validation = {
                "ok": False,
                "reason": current_policy.reason or f"Policy denied tool: {approval.tool_name}",
                "gate": "policy",
                "details": current_policy.details,
            }
            store.mark(approval_id, "invalid", details_update={"invalid_reason": validation["reason"], "invalid_gate": "policy"})
            raise ApprovalValidationError("invalid", validation)

        digest_validation = validate_effect_digest(approval.tool_name, approval.arguments, approval.details)
        if not digest_validation["ok"]:
            store.mark(approval_id, "invalid", details_update={
                "invalid_reason": digest_validation.get("reason") or "",
                "invalid_stored_digest": digest_validation.get("stored_digest") or "",
                "invalid_expected_digest": digest_validation.get("expected_digest") or "",
            })
            raise ApprovalValidationError("invalid", digest_validation)

        preview_validation = validate_tool_effect_preview(
            self.workspace,
            approval.tool_name,
            approval.arguments,
            approval.details.get("effect_preview"),
        )
        if not preview_validation["ok"]:
            store.mark(approval_id, "stale", details_update={
                "stale_reason": preview_validation.get("reason") or "",
                "stale_changed_fields": preview_validation.get("changed_fields") or [],
                "stale_current_preview": preview_validation.get("current_preview"),
            })
            raise ApprovalValidationError("stale", preview_validation)

        execution_id = str(uuid.uuid4())
        claimed = store.begin_execution(approval_id, execution_id=execution_id)
        execution_id = str(claimed.execution_id)
        call = ToolCall(
            id=claimed.tool_call_id,
            name=claimed.tool_name,
            arguments=dict(claimed.arguments),
        )
        try:
            if before_execute is not None:
                before_execute(call, execution_id)
            # The checkpoint/event callback can take observable time. Re-check
            # the exact preview after it and while the workspace lock is held so
            # an approved diff cannot overwrite a newer in-process file state.
            execution_preview_validation = validate_tool_effect_preview(
                self.workspace,
                claimed.tool_name,
                claimed.arguments,
                claimed.details.get("effect_preview"),
            )
            if not execution_preview_validation["ok"]:
                stale_details = {
                    "stale_reason": execution_preview_validation.get("reason") or "",
                    "stale_changed_fields": execution_preview_validation.get("changed_fields") or [],
                    "stale_current_preview": execution_preview_validation.get("current_preview"),
                    "stale_gate": "execution_boundary",
                }
                store.cancel_execution(
                    approval_id,
                    execution_id=execution_id,
                    status="stale",
                    details_update=stale_details,
                )
                raise ApprovalValidationError("stale", execution_preview_validation)
            result = self._execute_call(
                call,
                execution_id=execution_id,
                before_execute=None,
                transform_result=transform_result,
            )
            store.complete_execution(
                approval_id,
                execution_id=execution_id,
                result=self._serialize_result(result),
            )
        except ApprovalValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - persist failure before returning control
            store.fail_execution(approval_id, execution_id=execution_id, error=str(exc))
            raise ToolExecutionError(
                call=call,
                execution_id=execution_id,
                approval_id=approval_id,
                cause=exc,
            ) from exc
        return ExecutionOutcome(
            call=call,
            result=result,
            execution_id=execution_id,
            approval_id=approval_id,
        )

    def _execute_call(
        self,
        call: ToolCall,
        *,
        execution_id: str,
        before_execute: BeforeExecute | None,
        transform_result: TransformResult | None,
    ) -> ToolResult:
        # Registry validates again here as defense in depth against plan mutation.
        self.tool_registry.validate_arguments(call.name, call.arguments)
        if before_execute is not None:
            before_execute(call, execution_id)
        result = self.tool_registry.execute(call.name, call.arguments)
        result.tool_call_id = call.id
        if transform_result is not None:
            result = transform_result(call, result)
        return result

    def _require_approval_store(self) -> PendingApprovalStore:
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        return self.approval_store

    @staticmethod
    def _serialize_result(result: ToolResult) -> dict[str, Any]:
        return {
            "tool_name": result.tool_name,
            "content": result.content,
            "tool_call_id": result.tool_call_id,
            "is_error": result.is_error,
            "details": result.details,
        }

    @staticmethod
    def _stored_result(approval: PendingApproval, call: ToolCall) -> ToolResult:
        payload = approval.details.get("execution_result")
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Completed approval has no replayable execution result: {approval.approval_id}"
            )
        return ToolResult(
            tool_name=str(payload.get("tool_name") or call.name),
            content=str(payload.get("content") or ""),
            tool_call_id=str(payload.get("tool_call_id") or call.id),
            is_error=bool(payload.get("is_error", False)),
            details=dict(payload.get("details") or {}),
        )


def _workspace_execution_lock(workspace: Path) -> threading.RLock:
    """Return the process-wide lock that serializes approved workspace effects."""
    with _WORKSPACE_LOCKS_GUARD:
        return _WORKSPACE_EXECUTION_LOCKS.setdefault(workspace, threading.RLock())
