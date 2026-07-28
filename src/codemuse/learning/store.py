"""JSONL persistence and review state for learning candidates."""
from __future__ import annotations

import json
from pathlib import Path

from codemuse.learning.models import LearningCandidate


class LearningStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.candidates_path = self.root / "candidates.jsonl"
        self.processed_path = self.root / "processed_turns.json"

    def append(self, candidates: list[LearningCandidate]) -> None:
        if not candidates:
            return
        existing = {self._normalized(item.content) for item in self.list()}
        additions = [item for item in candidates if self._normalized(item.content) not in existing]
        if not additions:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self.candidates_path.open("a", encoding="utf-8") as handle:
            for candidate in additions:
                handle.write(json.dumps(candidate.to_dict(), ensure_ascii=False) + "\n")

    def list(self, *, status: str | None = None) -> list[LearningCandidate]:
        if not self.candidates_path.exists():
            return []
        items: list[LearningCandidate] = []
        for line in self.candidates_path.read_text(encoding="utf-8").splitlines():
            try:
                item = LearningCandidate.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if status is None or item.status == status:
                items.append(item)
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def get(self, candidate_id: str) -> LearningCandidate:
        candidate = next((item for item in self.list() if item.candidate_id == candidate_id), None)
        if candidate is None:
            raise FileNotFoundError(f"Learning candidate not found: {candidate_id}")
        return candidate

    def update(self, updated: LearningCandidate) -> None:
        items = self.list()
        if not any(item.candidate_id == updated.candidate_id for item in items):
            raise FileNotFoundError(f"Learning candidate not found: {updated.candidate_id}")
        self.root.mkdir(parents=True, exist_ok=True)
        ordered = [updated if item.candidate_id == updated.candidate_id else item for item in reversed(items)]
        self.candidates_path.write_text("".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in ordered), encoding="utf-8")

    def was_processed(self, session_id: str, turn_id: str) -> bool:
        return f"{session_id}:{turn_id}" in self._processed()

    def mark_processed(self, session_id: str, turn_id: str) -> None:
        values = self._processed()
        values.add(f"{session_id}:{turn_id}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.processed_path.write_text(json.dumps(sorted(values), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def summary(self) -> dict[str, int]:
        counts = {"pending": 0, "applied": 0, "rejected": 0}
        for item in self.list():
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    def _processed(self) -> set[str]:
        if not self.processed_path.exists():
            return set()
        try:
            payload = json.loads(self.processed_path.read_text(encoding="utf-8"))
            return {str(item) for item in payload if isinstance(item, str)} if isinstance(payload, list) else set()
        except (OSError, json.JSONDecodeError):
            return set()

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(value.lower().split())
