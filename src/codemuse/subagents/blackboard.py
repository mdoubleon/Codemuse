"""Structured handoff state shared by nodes in one orchestration run."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentManifest:
    agent: str
    status: str
    summary: str
    findings: list[str] = field(default_factory=list)
    inspected_paths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "status": self.status,
            "summary": self.summary,
            "findings": list(self.findings),
            "inspected_paths": list(self.inspected_paths),
            "risks": list(self.risks),
            "artifacts": list(self.artifacts),
        }


class Blackboard:
    def __init__(self) -> None:
        self._items: dict[str, AgentManifest] = {}

    def put(self, node_id: str, manifest: AgentManifest) -> None:
        self._items[node_id] = manifest

    def get(self, node_id: str) -> AgentManifest | None:
        return self._items.get(node_id)

    def dependency_context(self, node_ids: list[str]) -> list[dict[str, Any]]:
        return [self._items[node_id].to_dict() for node_id in node_ids if node_id in self._items]

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {node_id: item.to_dict() for node_id, item in self._items.items()}


__all__ = ["AgentManifest", "Blackboard"]
