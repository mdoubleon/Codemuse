"""Deterministic extraction of explicit durable user instructions."""
from __future__ import annotations

import re

from codemuse.learning.models import LearningCandidate
from codemuse.learning.safety import clean_learning_text, is_safe_learning_text


SIGNALS: tuple[tuple[str, str], ...] = (
    ("always", "project_convention"),
    ("never", "project_convention"),
    ("convention", "project_convention"),
    ("workflow", "workflow"),
    ("总是", "project_convention"),
    ("不要", "project_convention"),
    ("约定", "project_convention"),
    ("工作流", "workflow"),
    ("remember", "user_preference"),
    ("记住", "user_preference"),
)


class LearningExtractor:
    def extract(self, text: str, *, session_id: str, turn_id: str) -> list[LearningCandidate]:
        value = clean_learning_text(text, limit=2001)
        if not is_safe_learning_text(value):
            return []
        lowered = value.lower()
        match = next(((signal, kind) for signal, kind in SIGNALS if signal in lowered), None)
        if match is None:
            return []
        signal, kind = match
        content = _durable_clause(value, signal)
        if len(content) < 4:
            return []
        title = _title(content, kind)
        confidence = "high" if signal in {"remember", "记住", "always", "never", "总是", "不要"} else "medium"
        return [
            LearningCandidate(
                title=title,
                content=content,
                kind=kind,  # type: ignore[arg-type]
                confidence=confidence,
                evidence=value[:500],
                source_session_id=session_id,
                source_turn_id=turn_id,
            )
        ]


def _durable_clause(text: str, signal: str) -> str:
    start = text.lower().find(signal)
    selected = text[start:] if start >= 0 else text
    return selected.strip(" :-，。")[:1000]


def _title(content: str, kind: str) -> str:
    prefix = {"user_preference": "User preference", "project_convention": "Project convention", "workflow": "Workflow"}.get(kind, "Lesson")
    preview = re.sub(r"\s+", " ", content).strip()
    return f"{prefix}: {preview[:80]}" if preview else prefix
