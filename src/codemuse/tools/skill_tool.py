"""Runtime tools for discovered CodeMuse skills."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.app.skills_runtime import SkillRuntime
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class RunSkillTool(BaseTool):
    """Render a discovered SKILL.md as a bounded runtime instruction result."""

    def __init__(self, workspace: Path, runtime: SkillRuntime) -> None:
        super().__init__(workspace)
        self.runtime = runtime

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_skill",
            description="Load a discovered workspace skill and return its bounded instructions for the current task.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "task": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["name"],
            },
            permission_domain="read",
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("run_skill requires a skill name.")
        max_chars = max(200, min(12000, int(arguments.get("max_chars") or 4000)))
        result = self.runtime.run_skill(name=name, task=str(arguments.get("task") or ""), max_chars=max_chars)
        return ToolResult(
            tool_name=self.spec.name,
            content=result["content"],
            details=result,
        )


def register_skill_tools(registry, workspace: Path, runtime: SkillRuntime) -> None:
    """Register skill runtime tools."""
    registry.register(RunSkillTool(workspace, runtime), category="skill")

