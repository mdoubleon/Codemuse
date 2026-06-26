"""Data models for blueprint-derived project plans."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectPlanTask:
    task_id: str
    title: str
    phase: str
    description: str
    source_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "phase": self.phase,
            "description": self.description,
            "source_paths": list(self.source_paths),
            "depends_on": list(self.depends_on),
            "acceptance": list(self.acceptance),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectPlanTask":
        return cls(
            task_id=str(data["task_id"]),
            title=str(data["title"]),
            phase=str(data["phase"]),
            description=str(data["description"]),
            source_paths=list(data.get("source_paths") or []),
            depends_on=list(data.get("depends_on") or []),
            acceptance=list(data.get("acceptance") or []),
        )


@dataclass
class ProjectPlan:
    plan_id: str
    goal: str
    blueprint_id: str
    repo_id: str
    title: str
    summary: str
    tasks: list[ProjectPlanTask] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "blueprint_id": self.blueprint_id,
            "repo_id": self.repo_id,
            "title": self.title,
            "summary": self.summary,
            "tasks": [task.to_dict() for task in self.tasks],
            "risks": list(self.risks),
            "verification": list(self.verification),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectPlan":
        return cls(
            plan_id=str(data["plan_id"]),
            goal=str(data["goal"]),
            blueprint_id=str(data["blueprint_id"]),
            repo_id=str(data["repo_id"]),
            title=str(data["title"]),
            summary=str(data["summary"]),
            tasks=[ProjectPlanTask.from_dict(item) for item in data.get("tasks", [])],
            risks=list(data.get("risks") or []),
            verification=list(data.get("verification") or []),
            created_at=float(data.get("created_at") or time.time()),
        )
