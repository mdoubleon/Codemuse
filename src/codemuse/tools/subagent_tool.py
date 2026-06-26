"""Expose bounded subagent execution as normal runtime tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codemuse.subagents.manager import SubAgentManager
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class SpawnSubAgentTool(BaseTool):
    """Run one focused bounded subagent task."""

    def __init__(self, workspace: Path, manager: SubAgentManager) -> None:
        super().__init__(workspace)
        self.manager = manager

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="spawn_subagent",
            description="Run a bounded read-only subagent for a focused research task.",
            parameters={
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "task": {"type": "string"},
                    "max_turns": {"type": "integer"},
                },
                "required": ["task"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        task = str(arguments.get("task") or "").strip()
        if not task:
            raise ValueError("spawn_subagent requires a task.")
        max_turns = int(arguments["max_turns"]) if arguments.get("max_turns") is not None else None
        result = self.manager.run_sync(
            spec_name=str(arguments.get("agent") or "repo-researcher"),
            task=task,
            max_turns=max_turns,
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            details={"subagent_result": result.to_dict()},
        )


class RunSubAgentPlanTool(BaseTool):
    """Run a bounded sequence of read-only subagent tasks."""

    def __init__(self, workspace: Path, manager: SubAgentManager) -> None:
        super().__init__(workspace)
        self.manager = manager

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_subagent_plan",
            description="Run a sequence of bounded read-only subagent tasks and return an aggregate trace.",
            parameters={
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "tasks": {"type": "array", "items": {"type": "string"}},
                    "max_turns": {"type": "integer"},
                },
                "required": ["tasks"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        tasks = [str(item) for item in arguments.get("tasks", [])]
        max_turns = int(arguments["max_turns"]) if arguments.get("max_turns") is not None else None
        result = self.manager.run_plan(
            spec_name=str(arguments.get("agent") or "repo-researcher"),
            tasks=tasks,
            max_turns=max_turns,
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=json.dumps(result, ensure_ascii=False, indent=2),
            details={"subagent_plan": result},
        )


def register_subagent_tools(registry, workspace: Path, manager: SubAgentManager) -> None:
    registry.register(SpawnSubAgentTool(workspace, manager), category="subagent")
    registry.register(RunSubAgentPlanTool(workspace, manager), category="subagent")
