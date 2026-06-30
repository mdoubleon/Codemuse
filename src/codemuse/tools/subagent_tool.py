"""提供工具系统中 subagent tool 相关实现。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codemuse.subagents.manager import SubAgentManager
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class SpawnSubAgentTool(BaseTool):
    """Run one focused bounded subagent task."""

    def __init__(self, workspace: Path, manager: SubAgentManager) -> None:
        """初始化 SpawnSubAgentTool 并保存运行依赖。"""
        super().__init__(workspace)
        self.manager = manager

    @property
    def spec(self) -> ToolSpec:
        """返回 SpawnSubAgentTool 的 ToolSpec 声明。"""
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
        """执行 SpawnSubAgentTool 的工具逻辑并返回 ToolResult。"""
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
        """初始化 RunSubAgentPlanTool 并保存运行依赖。"""
        super().__init__(workspace)
        self.manager = manager

    @property
    def spec(self) -> ToolSpec:
        """返回 RunSubAgentPlanTool 的 ToolSpec 声明。"""
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
        """执行 RunSubAgentPlanTool 的工具逻辑并返回 ToolResult。"""
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
    """注册子 Agenttools。"""
    registry.register(SpawnSubAgentTool(workspace, manager), category="subagent")
    registry.register(RunSubAgentPlanTool(workspace, manager), category="subagent")
