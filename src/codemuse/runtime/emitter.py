"""Typed lifecycle publisher used by AgentRuntime and integrations."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from codemuse.domain.tools import ToolCall
from codemuse.runtime.events import AgentEvent
from codemuse.runtime.lifecycle import (
    ContextBuildDecision, ProviderRequestDecision, ProviderResponseDecision,
    SessionCompactDecision, ToolCallDecision, ToolErrorDecision,
    ToolResultDecision,
)
from codemuse.runtime.state import AgentState

LifecycleSubscriber = Callable[[AgentEvent], None]


class LifecycleEmitter:
    """Dispatch events and allow integrations to transform runtime decisions."""

    def __init__(self) -> None:
        self._subscribers: list[LifecycleSubscriber] = []
        self._handlers: dict[str, list[Callable[..., Any]]] = {
            "context_built": [], "before_provider_request": [],
            "provider_response": [], "tool_call": [], "tool_result": [],
            "tool_error": [], "session_before_compact": [],
        }

    def subscribe(self, callback: LifecycleSubscriber) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def on(self, event_type: str, callback: Callable[..., Any]) -> None:
        self._handlers.setdefault(event_type, []).append(callback)

    def on_context_built(self, callback: Callable[..., Any]) -> None: self.on("context_built", callback)
    def on_before_provider_request(self, callback: Callable[..., Any]) -> None: self.on("before_provider_request", callback)
    def on_provider_response(self, callback: Callable[..., Any]) -> None: self.on("provider_response", callback)
    def on_tool_call(self, callback: Callable[..., Any]) -> None: self.on("tool_call", callback)
    def on_tool_result(self, callback: Callable[..., Any]) -> None: self.on("tool_result", callback)
    def on_tool_error(self, callback: Callable[..., Any]) -> None: self.on("tool_error", callback)
    def on_session_before_compact(self, callback: Callable[..., Any]) -> None: self.on("session_before_compact", callback)

    def emit(self, event: AgentEvent) -> AgentEvent:
        for callback in tuple(self._subscribers):
            callback(event)
        return event

    @staticmethod
    def _merge(current: Any, decision: Any) -> Any:
        if decision is None:
            return current
        if getattr(decision, "details", None):
            current.details.update(decision.details)
        return decision

    def emit_context_built(self, event: AgentEvent, state: AgentState, messages: list[Any]) -> ContextBuildDecision:
        result = ContextBuildDecision(messages=messages)
        for callback in self._handlers["context_built"]:
            decision = callback(event, state, result.messages or messages)
            if isinstance(decision, list): result.messages = decision
            elif decision is not None:
                result = self._merge(result, decision)
                if getattr(decision, "messages", None) is not None: result.messages = decision.messages
        return result

    def emit_before_provider_request(self, event: AgentEvent, state: AgentState, messages: list[Any], tools: list[Any]) -> ProviderRequestDecision:
        result = ProviderRequestDecision(messages=messages, tools=tools)
        for callback in self._handlers["before_provider_request"]:
            decision = callback(event, state, result.messages or messages, result.tools or tools)
            if decision is not None:
                result = self._merge(result, decision)
                if getattr(decision, "messages", None) is not None: result.messages = decision.messages
                if getattr(decision, "tools", None) is not None: result.tools = decision.tools
        return result

    def emit_provider_response(self, event: AgentEvent, text: str, calls: list[ToolCall]) -> ProviderResponseDecision:
        result = ProviderResponseDecision(assistant_text=text, tool_calls=calls)
        for callback in self._handlers["provider_response"]:
            decision = callback(event, result.assistant_text or "", result.tool_calls or [])
            if decision is not None:
                result = self._merge(result, decision)
                if getattr(decision, "assistant_text", None) is not None: result.assistant_text = decision.assistant_text
                if getattr(decision, "tool_calls", None) is not None: result.tool_calls = decision.tool_calls
        return result

    def emit_tool_call(self, event: AgentEvent, state: AgentState, call: ToolCall, registry: Any) -> ToolCallDecision:
        result = ToolCallDecision()
        for callback in self._handlers["tool_call"]:
            decision = callback(event, state, call, registry)
            if decision is not None:
                result = self._merge(result, decision)
                if getattr(decision, "action", "allow") != "allow": return result
        return result

    def emit_tool_result(self, event: AgentEvent, state: AgentState, call: ToolCall, execution: Any) -> ToolResultDecision:
        result = ToolResultDecision(result=execution)
        for callback in self._handlers["tool_result"]:
            decision = callback(event, state, call, result.result or execution)
            if decision is not None:
                result.continue_loop = result.continue_loop and getattr(decision, "continue_loop", True)
                result = self._merge(result, decision)
                result.result = getattr(decision, "result", None) or result.result
        return result

    def emit_tool_error(self, event: AgentEvent, state: AgentState, call: ToolCall, error: Exception) -> ToolErrorDecision:
        result = ToolErrorDecision()
        for callback in self._handlers["tool_error"]:
            decision = callback(event, state, call, error)
            if decision is not None:
                result.continue_loop = result.continue_loop or getattr(decision, "continue_loop", False)
                result = self._merge(result, decision)
        return result

    def emit_session_before_compact(self, event: AgentEvent) -> SessionCompactDecision:
        result = SessionCompactDecision()
        for callback in self._handlers["session_before_compact"]:
            decision = callback(event)
            if decision is not None:
                result.allow = result.allow and getattr(decision, "allow", True)
                result = self._merge(result, decision)
        return result
