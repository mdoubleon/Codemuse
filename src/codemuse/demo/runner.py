"""Run a deterministic end-to-end CodeMuse demo in a temporary workspace."""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from codemuse.api import sdk


@dataclass(frozen=True)
class DemoStepResult:
    """One demo step result."""

    id: str
    title: str
    passed: bool
    duration_seconds: float
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DemoReport:
    """Structured demo report."""

    generated_at: str
    workspace: str
    total_steps: int
    passed: int
    failed: int
    duration_seconds: float
    steps: list[DemoStepResult]


StepHandler = Callable[[Path], dict[str, Any]]


def run_demo(*, output_dir: Path | None = None, save_report: bool = True) -> DemoReport:
    """Run the packaged five-minute demo in an isolated workspace."""
    started = time.perf_counter()
    steps: list[DemoStepResult] = []
    with tempfile.TemporaryDirectory(prefix="codemuse_demo_") as raw:
        workspace = Path(raw)
        _write_sample_repo(workspace)
        for step_id, title, handler in _demo_steps():
            step_started = time.perf_counter()
            try:
                details = handler(workspace)
                passed = True
                summary = str(details.pop("summary", "step passed"))
            except AssertionError as exc:
                passed = False
                summary = str(exc)
                details = {}
            except Exception as exc:  # pragma: no cover - defensive demo report path
                passed = False
                summary = f"{type(exc).__name__}: {exc}"
                details = {}
            steps.append(
                DemoStepResult(
                    id=step_id,
                    title=title,
                    passed=passed,
                    duration_seconds=time.perf_counter() - step_started,
                    summary=summary,
                    details=details,
                )
            )
        report = DemoReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            workspace=str(workspace),
            total_steps=len(steps),
            passed=sum(1 for item in steps if item.passed),
            failed=sum(1 for item in steps if not item.passed),
            duration_seconds=time.perf_counter() - started,
            steps=steps,
        )
        if save_report:
            write_demo_report(report, output_dir or Path("artifacts") / "demo")
        return report


def write_demo_report(report: DemoReport, output_dir: Path) -> tuple[Path, Path]:
    """Persist demo JSON and Markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    md_path = output_dir / "latest.md"
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: DemoReport) -> str:
    """Render a human-readable demo report."""
    lines = [
        "# CodeMuse Demo Report",
        "",
        f"- Generated at: `{report.generated_at}`",
        f"- Total steps: `{report.total_steps}`",
        f"- Pass / fail: `{report.passed}` / `{report.failed}`",
        f"- Duration: `{report.duration_seconds:.3f}s`",
        "",
        "| Step | Status | Summary |",
        "| --- | --- | --- |",
    ]
    for step in report.steps:
        status = "PASS" if step.passed else "FAIL"
        lines.append(f"| `{step.id}` | {status} | {step.summary} |")
    lines.append("")
    return "\n".join(lines)


def _demo_steps() -> list[tuple[str, str, StepHandler]]:
    """处理 演示步骤。"""
    return [
        ("workspace_read", "Read a local workspace", _step_workspace_read),
        ("github_import_plan", "Parse a GitHub import plan safely", _step_github_import_plan),
        ("project_plan", "Build a blueprint-derived project plan", _step_project_plan),
        ("approval_write", "Stage and approve a file write", _step_approval_write),
        ("checkpoint_rewind", "Create and rewind a workspace checkpoint", _step_checkpoint_rewind),
    ]


def _step_workspace_read(workspace: Path) -> dict[str, Any]:
    """处理 step工作区读取。"""
    payload = sdk.run("list files", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "list_files")
    _assert("README.md" in payload["assistant"], "list_files did not include README.md")
    return {"summary": "Agent listed workspace files.", "event_count": payload["event_count"]}


def _step_github_import_plan(workspace: Path) -> dict[str, Any]:
    """处理 stepgithub导入计划。"""
    payload = sdk.run("github import https://github.com/openai/codex/tree/main", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "prepare_repo_import")
    plan = event["details"]["import_plan"]
    _assert(plan["requires_network"] is True, "GitHub import plan should mark network as required")
    _assert(plan["import_ready"] is False, "demo import must not clone repositories")
    return {"summary": f"Prepared safe import plan for {plan['repo_id']}.", "repo_id": plan["repo_id"]}


def _step_project_plan(workspace: Path) -> dict[str, Any]:
    """处理 step项目计划。"""
    payload = sdk.run("project plan goal: add release readiness docs", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "build_project_plan")
    plan = event["details"]["plan"]
    _assert(plan["goal"] == "add release readiness docs", "project plan goal was not preserved")
    return {"summary": f"Generated project plan with {len(plan['tasks'])} tasks.", "task_count": len(plan["tasks"])}


def _step_approval_write(workspace: Path) -> dict[str, Any]:
    """处理 step审批写入。"""
    target = workspace / "notes" / "demo.txt"
    payload = sdk.run("write file notes/demo.txt content: hello from CodeMuse demo", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "write_file")
    _assert(not target.exists(), "file was written before approval")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "hello from CodeMuse demo\n", "approved write content did not match")
    _assert_event(approved, "tool_result", "write_file")
    return {"summary": "Write was staged, approved, and applied.", "approved_event_count": approved["event_count"]}


def _step_checkpoint_rewind(workspace: Path) -> dict[str, Any]:
    """处理 step检查点回退。"""
    target = workspace / "README.md"
    checkpoint = sdk.create_checkpoint(workspace, label="demo checkpoint", collect_events=True)
    checkpoint_id = str(_single_event(checkpoint, "checkpoint_created", None)["details"]["checkpoint_id"])
    before = target.read_text(encoding="utf-8")
    target.write_text("# Changed during demo\n", encoding="utf-8")
    rewind = sdk.rewind(workspace, checkpoint_id, session_id=checkpoint["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == before, "rewind did not restore README.md")
    _assert_event(rewind, "checkpoint_rewound", None)
    return {"summary": "Checkpoint restored workspace content.", "checkpoint_id": checkpoint_id}


def _write_sample_repo(root: Path) -> None:
    """写入sample仓库。"""
    (root / "README.md").write_text("# Sample Agent\n\nA tiny project for the CodeMuse demo.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")


def _single_event(payload: dict[str, Any], event_type: str, tool_name: str | None) -> dict[str, Any]:
    """提取单个事件。"""
    matches = [
        event
        for event in payload.get("events", [])
        if isinstance(event, dict)
        and event.get("type") == event_type
        and (tool_name is None or event.get("tool_name") == tool_name)
    ]
    _assert(len(matches) == 1, f"expected one {event_type}[{tool_name}], got {len(matches)}")
    return matches[0]


def _assert_event(payload: dict[str, Any], event_type: str, tool_name: str | None) -> None:
    """断言事件。"""
    for event in payload.get("events", []):
        if not isinstance(event, dict):
            continue
        if event.get("type") == event_type and (tool_name is None or event.get("tool_name") == tool_name):
            return
    raise AssertionError(f"missing event {event_type}[{tool_name}]")


def _assert(condition: bool, message: str) -> None:
    """断言演示流程。"""
    if not condition:
        raise AssertionError(message)

