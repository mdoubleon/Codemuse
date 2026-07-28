"""Best-effort learning extraction after a session has been persisted."""
from __future__ import annotations

from pathlib import Path

from codemuse.learning.extractor import LearningExtractor
from codemuse.learning.models import LearningCandidate
from codemuse.learning.store import LearningStore
from codemuse.memory.file_memory_store import FileMemoryStore
from codemuse.runtime.events import AgentEvent
from codemuse.storage.sessions import SessionStore


class LearningRuntime:
    def __init__(self, workspace: Path, *, session_store: SessionStore | None = None, store: LearningStore | None = None) -> None:
        self.workspace = workspace.resolve()
        data_root = self.workspace / ".data" / "codemuse"
        self.session_store = session_store or SessionStore(data_root / "sessions")
        self.store = store or LearningStore(data_root / "learning")
        self.extractor = LearningExtractor()

    def handle_event(self, event: AgentEvent) -> list[LearningCandidate]:
        if event.type != "agent_end" or event.turn_id is None or event.phase == "awaiting_approval":
            return []
        return self.on_turn_persisted(event.session_id, str(event.turn_id))

    def on_turn_persisted(self, session_id: str, turn_id: str) -> list[LearningCandidate]:
        if self.store.was_processed(session_id, turn_id):
            return []
        record = self.session_store.load(session_id)
        user_message = next((message for message in reversed(record.messages) if message.role == "user"), None)
        candidates = self.extractor.extract(user_message.text_content() if user_message else "", session_id=session_id, turn_id=turn_id)
        self.store.append(candidates)
        self.store.mark_processed(session_id, turn_id)
        return candidates

    def approve(self, candidate_id: str) -> LearningCandidate:
        candidate = self.store.get(candidate_id)
        if candidate.status != "pending":
            raise ValueError(f"Learning candidate is already {candidate.status}.")
        memory = FileMemoryStore(self.workspace / ".data" / "codemuse" / "project_memory").add(
            title=candidate.title,
            content=candidate.content,
            category=candidate.kind,
            tags=["learning", candidate.confidence],
            source="learning_review",
        )
        updated = candidate.reviewed("applied", memory_id=memory.memory_id)
        self.store.update(updated)
        return updated

    def reject(self, candidate_id: str) -> LearningCandidate:
        candidate = self.store.get(candidate_id)
        if candidate.status != "pending":
            raise ValueError(f"Learning candidate is already {candidate.status}.")
        updated = candidate.reviewed("rejected")
        self.store.update(updated)
        return updated
