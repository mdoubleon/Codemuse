"""Lifecycle event names and small decision objects used by the runtime.

The project intentionally keeps these objects as dataclasses so the runtime
does not acquire a dependency on a validation framework.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SESSION_START = "session_start"
SESSION_RESTORE = "session_restore"
SESSION_BEFORE_SWITCH = "session_before_switch"
SESSION_SWITCHED = "session_switched"
SESSION_BEFORE_FORK = "session_before_fork"
SESSION_FORKED = "session_forked"
SESSION_BEFORE_TREE = "session_before_tree"
SESSION_TREE_VIEWED = "session_tree_viewed"
SESSION_TREE_NAVIGATED = "session_tree_navigated"
SESSION_BEFORE_COMPACT = "session_before_compact"
SESSION_COMPACTED = "session_compacted"
SESSION_REWOUND = "session_rewound"
SESSION_SHUTDOWN = "session_shutdown"
AGENT_START = "agent_start"
TURN_START = "turn_start"
TURN_PHASE_CHANGED = "turn_phase_changed"
TURN_END = "turn_end"
AGENT_END = "agent_end"
CONTEXT_BUILT = "context_built"
BEFORE_PROVIDER_REQUEST = "before_provider_request"
PROVIDER_RESPONSE = "provider_response"
PROVIDER_ERROR = "provider_error"
TOOL_CALL = "tool_call"
TOOL_START = "tool_start"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
TOOL_END = "tool_end"
QUEUE_ENQUEUED = "queue_enqueued"
QUEUE_DEQUEUED = "queue_dequeued"
QUEUE_CLEARED = "queue_cleared"
MESSAGE_DELTA = "message_delta"
ERROR = "error"
COMPACTION = "compaction"
TURN_STATE = "turn_state"


@dataclass
class LifecycleDecision:
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextBuildDecision(LifecycleDecision):
    messages: list[Any] | None = None


@dataclass
class ProviderRequestDecision(LifecycleDecision):
    messages: list[Any] | None = None
    tools: list[Any] | None = None


@dataclass
class ProviderResponseDecision(LifecycleDecision):
    assistant_text: str | None = None
    tool_calls: list[Any] | None = None


@dataclass
class ToolCallDecision(LifecycleDecision):
    action: str = "allow"
    message: str | None = None


@dataclass
class ToolResultDecision(LifecycleDecision):
    continue_loop: bool = True
    result: Any = None


@dataclass
class ToolErrorDecision(LifecycleDecision):
    continue_loop: bool = False


@dataclass
class SessionCompactDecision(LifecycleDecision):
    allow: bool = True


__all__ = [name for name in globals() if name.isupper()] + [
    "LifecycleDecision", "ContextBuildDecision", "ProviderRequestDecision",
    "ProviderResponseDecision", "ToolCallDecision", "ToolResultDecision",
    "ToolErrorDecision", "SessionCompactDecision",
]
