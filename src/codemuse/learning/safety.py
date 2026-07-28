"""Conservative filters for durable-learning text."""
from __future__ import annotations

import re


SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|client[_-]?secret|access[_-]?token|password)\s*[:=]\s*['\"]?\S{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
TRANSIENT_PATTERNS = (
    re.compile(r"(?im)^traceback \(most recent call last\):"),
    re.compile(r"(?im)^\s*\[(?:debug|trace)\]"),
)


def clean_learning_text(text: str, *, limit: int = 1600) -> str:
    cleaned = "".join(char for char in str(text) if ord(char) >= 32 or char in {"\n", "\r", "\t"})
    return " ".join(cleaned.split())[:limit].strip()


def learning_text_rejection_reason(text: str, *, max_chars: int = 2000) -> str | None:
    value = str(text or "")
    if not value.strip():
        return "empty"
    if len(value) > max_chars:
        return "too_long"
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        return "possible_secret"
    if any(pattern.search(value) for pattern in TRANSIENT_PATTERNS):
        return "transient_log"
    if any(ord(char) < 32 and char not in {"\n", "\r", "\t"} for char in value):
        return "control_character"
    return None


def is_safe_learning_text(text: str) -> bool:
    return learning_text_rejection_reason(text) is None
