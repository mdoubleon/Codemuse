"""Data models for reviewable learning candidates."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Literal


LearningKind = Literal["project_convention", "lesson", "workflow", "user_preference"]
LearningStatus = Literal["pending", "applied", "rejected"]


@dataclass(frozen=True)
class LearningCandidate:
    title: str
    content: str
    kind: LearningKind = "lesson"
    confidence: str = "medium"
    evidence: str = ""
    source_session_id: str = ""
    source_turn_id: str = ""
    status: LearningStatus = "pending"
    candidate_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    reviewed_at: float | None = None
    memory_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "content": self.content,
            "kind": self.kind,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source_session_id": self.source_session_id,
            "source_turn_id": self.source_turn_id,
            "status": self.status,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "memory_id": self.memory_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LearningCandidate":
        return cls(
            candidate_id=str(payload["candidate_id"]),
            title=str(payload.get("title") or "Untitled learning"),
            content=str(payload.get("content") or ""),
            kind=str(payload.get("kind") or "lesson"),  # type: ignore[arg-type]
            confidence=str(payload.get("confidence") or "medium"),
            evidence=str(payload.get("evidence") or ""),
            source_session_id=str(payload.get("source_session_id") or ""),
            source_turn_id=str(payload.get("source_turn_id") or ""),
            status=str(payload.get("status") or "pending"),  # type: ignore[arg-type]
            created_at=float(payload.get("created_at") or time.time()),
            reviewed_at=float(payload["reviewed_at"]) if payload.get("reviewed_at") is not None else None,
            memory_id=str(payload["memory_id"]) if payload.get("memory_id") else None,
        )

    def reviewed(self, status: LearningStatus, *, memory_id: str | None = None) -> "LearningCandidate":
        return replace(self, status=status, memory_id=memory_id, reviewed_at=time.time())
