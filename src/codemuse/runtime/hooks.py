"""Composable context and tool hooks for CodeMuse extensions."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolCall
from codemuse.runtime.emitter import LifecycleEmitter
from codemuse.runtime.lifecycle import ToolCallDecision, ToolErrorDecision, ToolResultDecision


@dataclass
class BeforeToolCallDecision:
    action: str = "allow"
    message: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class AfterToolCallDecision:
    continue_loop: bool = True
    details: dict[str, Any] | None = None


@dataclass
class HookToolErrorDecision:
    continue_loop: bool = False
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ContextHookEntry:
    name: str
    kind: str
    fn: Callable[[Any, list[ChatMessage]], list[ChatMessage]]
    enabled_for_subagent: bool = False

    def __call__(self, state: Any, messages: list[ChatMessage]) -> list[ChatMessage]:
        return self.fn(state, messages)


class RuntimeHooks:
    def __init__(self, transform_context: list[Callable] | None = None, before_tool_call: list[Callable] | None = None, after_tool_call: list[Callable] | None = None, on_tool_error: list[Callable] | None = None, lifecycle_event: list[Callable] | None = None) -> None:
        self.transform_context_hooks = list(transform_context or [])
        self.before_tool_call_hooks = list(before_tool_call or [])
        self.after_tool_call_hooks = list(after_tool_call or [])
        self.on_tool_error_hooks = list(on_tool_error or [])
        self.lifecycle_event_hooks = list(lifecycle_event or [])

    def snapshot(self) -> dict[str, list[Callable]]:
        return {"transform_context": list(self.transform_context_hooks), "before_tool_call": list(self.before_tool_call_hooks), "after_tool_call": list(self.after_tool_call_hooks), "on_tool_error": list(self.on_tool_error_hooks), "lifecycle_event": list(self.lifecycle_event_hooks)}

    def restore(self, snapshot: dict[str, list[Callable]]) -> None:
        for key in ("transform_context", "before_tool_call", "after_tool_call", "on_tool_error", "lifecycle_event"):
            setattr(self, f"{key}_hooks", list(snapshot.get(key, [])))

    def add_transform_context_hook(self, name: str, kind: str, fn: Callable, *, enabled_for_subagent: bool = False) -> None:
        self.transform_context_hooks.append(ContextHookEntry(name, kind, fn, enabled_for_subagent))

    def transform_context(self, state: Any, messages: list[ChatMessage]) -> list[ChatMessage]:
        current = messages
        for hook in self.transform_context_hooks:
            current = hook(state, current)
        return current

    def before_tool_call(self, state: Any, call: ToolCall, registry: Any) -> BeforeToolCallDecision:
        final = BeforeToolCallDecision()
        for hook in self.before_tool_call_hooks:
            decision = hook(state, call, registry)
            if decision is None: continue
            final.details = {**(final.details or {}), **(getattr(decision, "details", {}) or {})}
            if getattr(decision, "action", "allow") != "allow":
                final.action, final.message = decision.action, getattr(decision, "message", None)
                return final
        return final

    def after_tool_call(self, state: Any, call: ToolCall, result: Any) -> AfterToolCallDecision:
        final = AfterToolCallDecision()
        for hook in self.after_tool_call_hooks:
            decision = hook(state, call, result)
            if decision is None: continue
            final.continue_loop = final.continue_loop and getattr(decision, "continue_loop", True)
            final.details = {**(final.details or {}), **(getattr(decision, "details", {}) or {})}
        return final

    def on_tool_error(self, state: Any, call: ToolCall, error: Exception) -> HookToolErrorDecision:
        final = HookToolErrorDecision()
        for hook in self.on_tool_error_hooks:
            decision = hook(state, call, error)
            if decision is None: continue
            final.continue_loop = final.continue_loop or getattr(decision, "continue_loop", False)
            final.details = {**(final.details or {}), **(getattr(decision, "details", {}) or {})}
        return final

    def register_with_lifecycle(self, emitter: LifecycleEmitter) -> None:
        emitter.subscribe(lambda event: [hook(event) for hook in self.lifecycle_event_hooks])
        emitter.on_context_built(lambda _event, state, messages: type("Decision", (), {"messages": self.transform_context(state, messages), "details": {}})())
        emitter.on_tool_call(lambda _event, state, call, registry: self._lifecycle_tool_call(state, call, registry))
        emitter.on_tool_result(lambda _event, state, call, result: self._lifecycle_tool_result(state, call, result))
        emitter.on_tool_error(lambda _event, state, call, error: self._lifecycle_tool_error(state, call, error))

    def _lifecycle_tool_call(self, state: Any, call: ToolCall, registry: Any) -> ToolCallDecision:
        d = self.before_tool_call(state, call, registry)
        return ToolCallDecision(action=d.action, message=d.message, details=d.details or {})

    def _lifecycle_tool_result(self, state: Any, call: ToolCall, result: Any) -> ToolResultDecision:
        d = self.after_tool_call(state, call, result)
        return ToolResultDecision(continue_loop=d.continue_loop, details=d.details or {}, result=result)

    def _lifecycle_tool_error(self, state: Any, call: ToolCall, error: Exception) -> ToolErrorDecision:
        d = self.on_tool_error(state, call, error)
        return ToolErrorDecision(continue_loop=d.continue_loop, details=d.details or {})
