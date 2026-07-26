"""Small, dependency-free turn decisions shared by CLI and Web workers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TurnDecision:
    action: str
    queued_message: Any = None
    reason: str = ""
    phase: str = "idle"


class TurnController:
    def on_turn_start(self, state: Any) -> TurnDecision:
        return TurnDecision("continue", reason="turn_start", phase="planning")

    def on_continue_request(self, state: Any, next_message: Any = None) -> TurnDecision:
        if getattr(state, "pending_tool_calls", None): return TurnDecision("resume_current", reason="pending_state", phase="executing")
        if next_message is not None: return TurnDecision("inject_message", next_message, "queued_message", "draining_queue")
        return TurnDecision("resume_current", reason="no_queue", phase="planning")

    def before_plan_approval(self) -> TurnDecision:
        return TurnDecision("pause", reason="planner_approval", phase="awaiting_approval")

    def before_tool_execution(self) -> TurnDecision:
        return TurnDecision("continue", reason="tool_execution", phase="executing")

    def after_assistant_turn(self, next_message: Any = None) -> TurnDecision:
        if next_message is not None: return TurnDecision("inject_message", next_message, "queued_message", "draining_queue")
        return TurnDecision("stop", reason="idle", phase="idle")

    def after_tool_round(self, *, tool_failed: bool, continue_after_error: bool = False, steering_message: Any = None) -> TurnDecision:
        if steering_message is not None and not tool_failed: return TurnDecision("inject_message", steering_message, "post_turn_steering", "draining_queue")
        if tool_failed and not continue_after_error: return TurnDecision("stop", reason="tool_error", phase="idle")
        return TurnDecision("continue", reason="continue_loop", phase="planning")

    def on_turn_end(self) -> TurnDecision:
        return TurnDecision("stop", reason="turn_end", phase="idle")
