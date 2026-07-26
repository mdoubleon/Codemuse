"""Read-only runtime control summaries and safe queue operations."""
from __future__ import annotations

from typing import Any


def summarize_runtime_control(*, pending_plan_token: str | None, pending_tool_call_count: int, queued_message_count: int, busy: bool, cancel_requested: bool, turn_phase: str, pending_artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    artifacts = pending_artifacts or []
    if cancel_requested: status = "canceled"
    elif artifacts: status = "awaiting_artifact_approval"
    elif pending_plan_token: status = "awaiting_plan_approval"
    elif busy or pending_tool_call_count: status = "executing" if turn_phase != "planning" else "planning"
    else: status = turn_phase or "idle"
    return {"status": status, "turn_phase": turn_phase, "busy": bool(busy), "cancel_requested": bool(cancel_requested), "pending_plan_token": pending_plan_token, "pending_tool_call_count": int(pending_tool_call_count), "queued_message_count": int(queued_message_count), "pending_artifact_count": len(artifacts), "pending_artifacts": artifacts}


def build_runtime_control(state: Any, *, cancel_requested: bool = False) -> dict[str, Any]:
    return summarize_runtime_control(pending_plan_token=getattr(state, "pending_plan_token", None), pending_tool_call_count=len(getattr(state, "pending_tool_calls", [])), queued_message_count=len(getattr(state, "queued_messages", [])), busy=bool(getattr(state, "is_running", False)), cancel_requested=cancel_requested, turn_phase=str(getattr(state, "phase", "idle")))
