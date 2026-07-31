"""提供工具系统中 subagent tool 相关实现。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codemuse.subagents.manager import SubAgentManager
from codemuse.subagents.orchestrator import SubAgentOrchestrator
from codemuse.subagents.worktree import WorktreeManager
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
                    "parallel": {"type": "boolean"},
                    "max_workers": {"type": "integer"},
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
            parallel=bool(arguments.get("parallel", True)),
            max_workers=int(arguments.get("max_workers") or 4),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=json.dumps(result, ensure_ascii=False, indent=2),
            details={"subagent_plan": result},
        )


class OrchestrateAgentsTool(BaseTool):
    """Run an explicit bounded workflow with dependency-aware handoffs."""

    def __init__(self, workspace: Path, manager: SubAgentManager) -> None:
        super().__init__(workspace)
        self.orchestrator = SubAgentOrchestrator(manager)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="orchestrate_agents",
            description="Run bounded research, debug, or code-change subagent workflows.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "workflow": {"type": "string", "enum": ["research", "debug", "code_change"]},
                    "max_agents": {"type": "integer"},
                    "allow_edits": {"type": "boolean"},
                },
                "required": ["goal"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        goal = str(arguments.get("goal") or "").strip()
        if not goal:
            raise ValueError("orchestrate_agents requires a goal")
        if bool(arguments.get("allow_edits", False)):
            raise PermissionError(
                "Use orchestrate_code_change for isolated code changes; it requires explicit approval."
            )
        result = self.orchestrator.run(
            goal=goal,
            workflow=str(arguments.get("workflow") or "research"),
            max_agents=int(arguments.get("max_agents") or 4),
            allow_edits=False,
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=json.dumps(result, ensure_ascii=False, indent=2),
            details={"orchestration": result},
        )


class OrchestrateCodeChangeTool(BaseTool):
    """Run the editable workflow only after the normal exact-effect approval."""

    def __init__(self, workspace: Path, manager: SubAgentManager) -> None:
        super().__init__(workspace)
        self.orchestrator = SubAgentOrchestrator(manager)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="orchestrate_code_change",
            description=(
                "Research, plan, implement in an isolated Git worktree, and review a code change. "
                "The parent workspace is unchanged until a reviewed patch artifact is separately approved."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "minLength": 1},
                    "max_agents": {"type": "integer", "minimum": 1, "maximum": 4},
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        goal = str(arguments.get("goal") or "").strip()
        if not goal:
            raise ValueError("orchestrate_code_change requires a goal")
        result = self.orchestrator.run(
            goal=goal,
            workflow="code_change",
            max_agents=int(arguments.get("max_agents") or 4),
            allow_edits=True,
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=json.dumps(result, ensure_ascii=False, indent=2),
            details={"orchestration": result},
        )


class ApplyPatchArtifactTool(BaseTool):
    """Apply a staged worktree patch after the normal CodeMuse approval flow."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="apply_patch_artifact",
            description="Apply a reviewed patch artifact produced by an isolated subagent worktree.",
            parameters={"type": "object", "properties": {"artifact_id": {"type": "string"}}, "required": ["artifact_id"]},
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        manager = WorktreeManager(self.workspace)
        artifact = manager.load_artifact(str(arguments.get("artifact_id") or ""))
        if artifact.status == "applied":
            raise ValueError(f"Patch artifact already applied: {artifact.artifact_id}")
        if artifact.review_status != "approved":
            raise PermissionError(
                f"Patch artifact has not passed review: {artifact.artifact_id} ({artifact.review_status})"
            )
        if not manager.apply_check(artifact):
            raise RuntimeError("Patch artifact no longer applies cleanly to the parent workspace")
        if not manager.apply(artifact):
            raise RuntimeError("Failed to apply patch artifact")
        manager.update_status(artifact, "applied")
        manager.cleanup(artifact)
        return ToolResult(
            tool_name=self.spec.name,
            content=f"Applied patch artifact {artifact.artifact_id}.",
            details={"artifact": artifact.to_dict(), "changed_paths": artifact.changed_paths},
        )

def register_subagent_tools(registry, workspace: Path, manager: SubAgentManager) -> None:
    """注册子 Agenttools。"""
    registry.register(SpawnSubAgentTool(workspace, manager), category="subagent")
    registry.register(RunSubAgentPlanTool(workspace, manager), category="subagent")
    registry.register(OrchestrateAgentsTool(workspace, manager), category="subagent")
    registry.register(OrchestrateCodeChangeTool(workspace, manager), category="subagent")
    registry.register(ApplyPatchArtifactTool(workspace), category="subagent")
