"""Deterministic conversation compaction for long-running sessions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codemuse.domain.messages import ChatMessage, TextPart


@dataclass
class CompactionResult:
    messages: list[ChatMessage]
    compacted: bool
    removed_messages: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"compacted": self.compacted, "removed_messages": self.removed_messages, "summary": self.summary}


class ConversationCompactor:
    """Keep the latest turns and a concise, searchable summary of older turns."""

    def __init__(self, *, threshold_tokens: int = 12000, keep_messages: int = 12, summary_chars: int = 4000) -> None:
        self.threshold_tokens = max(1, threshold_tokens)
        self.keep_messages = max(2, keep_messages)
        self.summary_chars = max(256, summary_chars)

    def should_compact(self, messages: list[ChatMessage], estimate_tokens: Any) -> bool:
        return estimate_tokens(messages) > self.threshold_tokens and len(messages) > self.keep_messages

    def compact(self, messages: list[ChatMessage], estimate_tokens: Any) -> CompactionResult:
        if not self.should_compact(messages, estimate_tokens):
            return CompactionResult(messages=list(messages), compacted=False)
        split = max(0, len(messages) - self.keep_messages)
        older, recent = messages[:split], messages[split:]
        lines: list[str] = []
        for message in older:
            text = message.text_content().replace("\n", " ").strip()
            if not text and message.tool_calls:
                text = "requested tools: " + ", ".join(call.name for call in message.tool_calls)
            if text:
                lines.append(f"{message.role}: {text[:360]}")
        summary = "\n".join(lines)[-self.summary_chars:]
        summary_message = ChatMessage(
            role="assistant",
            content=[TextPart(text="[conversation summary]\n" + summary)],
            metadata={"compacted": True, "source_message_count": len(older)},
        )
        return CompactionResult(messages=[summary_message, *recent], compacted=True, removed_messages=len(older), summary=summary)

    # Compatibility alias used by integrations that call the pp-Echo name.
    compact_messages = compact
