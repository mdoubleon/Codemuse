"""定义子 Agent 的规格、工具 allowlist 和执行结果结构。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubAgentSpec:
    """子 Agent 的能力边界。

    Spec 不执行任务，只声明这个子 Agent 是谁、能用哪些工具、最多跑几轮。
    """

    name: str
    description: str
    system_prompt: str
    tool_allowlist: list[str] = field(default_factory=list)
    max_turns: int = 3


@dataclass
class SubAgentRunResult:
    """SubAgentRunResult：表示一次执行后返回给上层的结构化结果。"""
    run_id: str
    spec_name: str
    task: str
    summary: str
    status: str = "completed"
    findings: list[str] = field(default_factory=list)
    used_tools: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        spec_name: str,
        task: str,
        summary: str,
        status: str = "completed",
        findings: list[str] | None = None,
        used_tools: list[str] | None = None,
        events: list[dict[str, Any]] | None = None,
        started_at: float | None = None,
    ) -> "SubAgentRunResult":
        """创建一条新的领域记录或运行结果。"""
        return cls(
            run_id=str(uuid.uuid4()),
            spec_name=spec_name,
            task=task,
            summary=summary,
            status=status,
            findings=findings or [],
            used_tools=used_tools or [],
            events=events or [],
            started_at=started_at or time.time(),
            completed_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        """把 SubAgentRunResult 转成可写入文件或 API 响应的字典。"""
        return {
            "run_id": self.run_id,
            "spec_name": self.spec_name,
            "task": self.task,
            "summary": self.summary,
            "status": self.status,
            "findings": self.findings,
            "used_tools": self.used_tools,
            "events": self.events,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


def default_subagent_specs() -> dict[str, SubAgentSpec]:
    """CodeMuse Stage 10 先提供只读研究型子 Agent。"""

    repo_researcher = SubAgentSpec(
        name="repo-researcher",
        description="Read-only subagent for inspecting repository files and summarizing relevant evidence.",
        system_prompt=(
            "You are repo-researcher, a bounded read-only subagent. "
            "Use file inspection tools to collect evidence and return a concise summary. "
            "Do not modify files and do not spawn other agents."
        ),
        tool_allowlist=["list_files", "read_file", "search_text", "search_project_memory", "search_blueprint_memory"],
        max_turns=3,
    )
    return {repo_researcher.name: repo_researcher}
