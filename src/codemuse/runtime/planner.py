"""Compile model tool requests into validated, policy-gated execution plans."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.domain.tools import ToolCall
from codemuse.tools.effects import build_effect_digest, build_tool_effect_preview
from codemuse.tools.policy import ALLOW, ASK, DENY, ToolPolicyEvaluator
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.validation import ToolArgumentValidationError


@dataclass(frozen=True)
class PlannedToolCall:
    """A model request after argument validation and policy evaluation."""

    call: ToolCall
    action: str
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    validation_errors: tuple[str, ...] = ()
    effect_preview: dict[str, Any] | None = None
    effect_digest: str | None = None

    @property
    def executable(self) -> bool:
        return self.action in {ALLOW, ASK}

    @property
    def validated_arguments(self) -> dict[str, Any]:
        """Convenience view used by integrations that do not need the full ToolCall."""
        return self.call.arguments

    @property
    def policy_action(self) -> str:
        return self.action

    @property
    def requires_approval(self) -> bool:
        return self.action == ASK

    def approval_details(self, *, plan_id: str) -> dict[str, Any]:
        """Return the immutable effect contract persisted in the approval queue."""
        if not self.requires_approval or not self.effect_digest:
            raise ValueError(f"Planned call does not require approval: {self.call.name}")
        details = {
            **self.details,
            "plan_id": plan_id,
            "effect_digest": self.effect_digest,
            "exact_effect_approval": True,
        }
        if self.effect_preview is not None:
            details["effect_preview"] = self.effect_preview
        return details

    def to_dict(self) -> dict[str, Any]:
        return {
            "call": self.call.to_dict(),
            "action": self.action,
            "reason": self.reason,
            "details": dict(self.details),
            "validation_errors": list(self.validation_errors),
            "effect_preview": self.effect_preview,
            "effect_digest": self.effect_digest,
        }


@dataclass(frozen=True)
class Plan:
    """Planner output consumed by the Executor, never raw provider tool calls."""

    plan_id: str
    session_id: str
    turn_id: int
    tool_calls: tuple[PlannedToolCall, ...]
    assistant_text: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def requires_approval(self) -> bool:
        return any(item.requires_approval for item in self.tool_calls)

    @property
    def calls(self) -> tuple[PlannedToolCall, ...]:
        """Alias emphasizing that the plan contains executable call IR."""
        return self.tool_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "assistant_text": self.assistant_text,
            "tool_calls": [item.to_dict() for item in self.tool_calls],
            "created_at": self.created_at,
        }


class Planner:
    """Own validation, policy gates, and exact-effect approval preparation."""

    def __init__(
        self,
        *,
        workspace: Path,
        tool_registry: ToolRegistry,
        policy_evaluator: ToolPolicyEvaluator,
    ) -> None:
        self.workspace = workspace.resolve()
        self.tool_registry = tool_registry
        self.policy_evaluator = policy_evaluator

    def create_plan(
        self,
        *,
        session_id: str,
        turn_id: int,
        tool_calls: list[ToolCall],
        assistant_text: str = "",
    ) -> Plan:
        """Compile provider output into a plan without executing any tool."""
        plan_id = str(uuid.uuid4())
        planned = tuple(self._plan_call(call) for call in tool_calls)
        return Plan(
            plan_id=plan_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_calls=planned,
            assistant_text=assistant_text,
        )

    def plan(
        self,
        *,
        session_id: str,
        turn_id: int,
        tool_calls: list[ToolCall],
        assistant_text: str = "",
    ) -> Plan:
        """Short alias for callers that treat planning as the primary operation."""
        return self.create_plan(
            session_id=session_id,
            turn_id=turn_id,
            tool_calls=tool_calls,
            assistant_text=assistant_text,
        )

    def _plan_call(self, call: ToolCall) -> PlannedToolCall:
        try:
            spec = self.tool_registry.get_spec(call.name)
        except (KeyError, ValueError) as exc:
            reason = str(exc)
            return PlannedToolCall(
                call=call,
                action=DENY,
                reason=reason,
                details={"gate": "tool_lookup", "tool_name": call.name},
                validation_errors=(reason,),
            )

        try:
            validated = self.tool_registry.validate_arguments(call.name, call.arguments)
        except ToolArgumentValidationError as exc:
            return PlannedToolCall(
                call=call,
                action=DENY,
                reason=str(exc),
                details={
                    "gate": "argument_validation",
                    "tool_name": call.name,
                    "validation_errors": list(exc.errors),
                },
                validation_errors=exc.errors,
            )

        validated_call = ToolCall(id=call.id, name=call.name, arguments=validated)
        decision = self.policy_evaluator.evaluate(spec)
        details = {**decision.details, "gate": "policy", "tool_name": call.name}
        if decision.action != ASK:
            return PlannedToolCall(
                call=validated_call,
                action=decision.action,
                reason=decision.reason,
                details=details,
            )

        preview = build_tool_effect_preview(self.workspace, call.name, validated)
        digest = build_effect_digest(call.name, validated, preview)
        return PlannedToolCall(
            call=validated_call,
            action=ASK,
            reason=decision.reason,
            details=details,
            effect_preview=preview,
            effect_digest=digest,
        )
