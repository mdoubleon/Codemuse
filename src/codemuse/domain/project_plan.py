"""Data models for blueprint-derived project plans."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectPlanTask:
    """定义 ProjectPlanTask的结构化数据。"""
    task_id: str
    title: str
    phase: str
    description: str
    source_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """将 ProjectPlanTask 转换为可序列化字典。"""
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
        """从字典数据恢复 ProjectPlanTask。"""
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
    """定义 ProjectPlan的结构化数据。"""
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
        """将 ProjectPlan 转换为可序列化字典。"""
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
        """从字典数据恢复 ProjectPlan。"""
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
