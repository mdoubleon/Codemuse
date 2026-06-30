"""Deterministic baseline eval runner for CodeMuse."""
from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from codemuse.api import sdk
from codemuse.benchmarks.models import BaselineCase, BaselineCaseResult, BaselineReport
from codemuse.benchmarks.report import build_report, write_report
from codemuse.demo.runner import run_demo
from codemuse.server.http import CodeMuseServer
from codemuse.server.session_manager import WebSessionManager

CaseHandler = Callable[[Path], dict[str, object]]


def default_cases() -> list[BaselineCase]:
    """构造默认用例。"""
    return [
        BaselineCase("file_list", "List workspace files", "tools", "FakeLLM selects list_files."),
        BaselineCase("read_file", "Read README", "tools", "FakeLLM selects read_file."),
        BaselineCase("search_text_match", "Search text match", "tools", "search_text returns matching lines."),
        BaselineCase("search_text_no_match", "Search text no match", "tools", "search_text reports no matches."),
        BaselineCase("read_source_file", "Read source file", "tools", "read_file can read nested source files."),
        BaselineCase("read_docs_file", "Read docs file", "tools", "read_file can read docs files."),
        BaselineCase("list_ignored_data", "List ignores managed data", "tools", "list_files hides .data content."),
        BaselineCase("list_nested_depth", "List nested files", "tools", "list_files includes nested project files."),
        BaselineCase("write_approval", "Write file approval", "approval", "write_file waits for approval."),
        BaselineCase("write_reject", "Reject file write", "approval", "rejected write_file does not touch disk."),
        BaselineCase("write_nested_approval", "Nested write approval", "approval", "write_file can create parent directories after approval."),
        BaselineCase("write_update_existing_approval", "Update existing file", "approval", "write_file updates existing files after approval."),
        BaselineCase("write_stale_after_target_change", "Write stale guard", "approval", "write_file approval goes stale if target changes."),
        BaselineCase("replace_approval", "Replace text approval", "approval", "replace_text waits for approval."),
        BaselineCase("replace_reject", "Reject replace text", "approval", "rejected replace_text leaves file unchanged."),
        BaselineCase("replace_all_approval", "Replace all text", "approval", "replace_text replace_all edits every match."),
        BaselineCase("replace_missing_text_blocked", "Blocked replace text", "approval", "replace_text preview blocks missing old_text."),
        BaselineCase("apply_patch_create_approval", "Apply patch create", "approval", "apply_patch creates files after approval."),
        BaselineCase("apply_patch_update_approval", "Apply patch update", "approval", "apply_patch updates files after approval."),
        BaselineCase("apply_patch_reject", "Reject apply patch", "approval", "rejected apply_patch leaves disk unchanged."),
        BaselineCase("apply_patch_stale_after_change", "Apply patch stale guard", "approval", "apply_patch approval goes stale if context changes."),
        BaselineCase("shell_blocked", "Blocked shell command", "safety", "destructive shell stays blocked."),
        BaselineCase("shell_safe_command", "Safe shell command", "safety", "low-risk shell command executes after approval."),
        BaselineCase("shell_empty_blocked", "Empty shell blocked", "safety", "empty shell command preview is blocked."),
        BaselineCase("shell_write_risk_preview", "Shell write risk preview", "safety", "shell write-like command is flagged in preview."),
        BaselineCase("shell_network_risk_preview", "Shell network risk preview", "safety", "shell network command is flagged in preview."),
        BaselineCase("checkpoint_rewind", "Workspace rewind", "rewind", "checkpoint restores workspace files."),
        BaselineCase("checkpoint_list_after_create", "List checkpoint", "rewind", "created checkpoints appear in SDK lists."),
        BaselineCase("rewind_restores_nested_file", "Nested rewind", "rewind", "rewind restores nested workspace files."),
        BaselineCase("multiple_checkpoint_rewind", "Multiple checkpoint rewind", "rewind", "rewind can target an earlier checkpoint."),
        BaselineCase("project_memory", "Project memory save/search", "memory", "memory tool approval and search."),
        BaselineCase("project_memory_recall_context", "Project memory recall", "memory", "memory recall is injected into later prompts."),
        BaselineCase("project_memory_no_match", "Project memory miss", "memory", "memory search can report no matches."),
        BaselineCase("save_blueprint_memory", "Save blueprint memory", "memory", "repo blueprint memory can be saved."),
        BaselineCase("search_blueprint_memory", "Search blueprint memory", "memory", "saved blueprint memory can be searched."),
        BaselineCase("blueprint_analysis", "Repo blueprint analysis", "memory", "repo blueprint analyzer returns structured details."),
        BaselineCase("repo_index", "Repository index", "repo", "repo index returns structural facts."),
        BaselineCase("blueprint_memory_empty_search", "Blueprint memory miss", "memory", "blueprint memory search handles no matches."),
        BaselineCase("memory_index_pipeline", "Memory index pipeline", "memory", "workspace files are indexed and retrieved through hybrid RAG."),
        BaselineCase("subagent", "Subagent read-only run", "subagent", "spawn_subagent uses allowlisted tools."),
        BaselineCase("subagent_read_file", "Subagent read file", "subagent", "subagent can use read_file."),
        BaselineCase("subagent_search_text", "Subagent search text", "subagent", "subagent can use search_text."),
        BaselineCase("subagent_plan", "Subagent plan", "subagent", "run_subagent_plan executes multiple bounded tasks."),
        BaselineCase("web_private_block", "Private web fetch block", "web", "private URL fetch is stale after approve."),
        BaselineCase("web_invalid_url_block", "Invalid web fetch block", "web", "invalid URL fetch is blocked in preview."),
        BaselineCase("web_public_preview", "Public web fetch preview", "web", "public URL fetch creates a non-blocked approval preview."),
        BaselineCase("repo_import_plan", "Repository import plan", "repo", "GitHub source becomes a safe import plan."),
        BaselineCase("repo_import_shorthand", "Repository shorthand import", "repo", "owner/name shorthand becomes a GitHub import plan."),
        BaselineCase("repo_import_ssh", "Repository SSH import", "repo", "git@github.com source becomes a GitHub import plan."),
        BaselineCase("repo_import_branch_nested", "Repository branch import", "repo", "tree URLs preserve branch paths."),
        BaselineCase("repo_import_local_ready", "Local repository import", "repo", "local workspace source is import-ready."),
        BaselineCase("repo_import_local_cache", "Local repository import cache", "repo", "approved local import writes imports and cache metadata."),
        BaselineCase("repo_git_status", "Repository git status", "repo", "repo_git_status returns safe metadata for a workspace."),
        BaselineCase("project_plan", "Blueprint project plan", "planning", "repo blueprint becomes a task plan."),
        BaselineCase("project_plan_goal_preserved", "Project plan goal", "planning", "project plan preserves a specific goal."),
        BaselineCase("web_ui_smoke", "Minimal Web UI smoke", "web", "static UI and /api session loop work."),
        BaselineCase("web_api_session_list", "Web API session list", "web", "HTTP API can create and list sessions."),
        BaselineCase("web_api_approval_flow", "Web API approval flow", "web", "HTTP API exposes pending approvals."),
        BaselineCase("web_api_checkpoint_flow", "Web API checkpoint flow", "web", "HTTP API can create checkpoints."),
        BaselineCase("capability_catalog", "Capability catalog", "capabilities", "tools, skills, extensions are listed."),
        BaselineCase("capability_kind_filter_builtin", "Capability kind filter", "capabilities", "capability catalog filters by kind."),
        BaselineCase("skill_runtime_execution", "Skill runtime execution", "skills", "run_skill loads a discovered SKILL.md."),
        BaselineCase("extension_runtime_execution", "Extension runtime execution", "extensions", "run_extension executes a safe manifest template."),
        BaselineCase("extension_dynamic_tool", "Extension dynamic tool", "extensions", "manifest-declared extension tools are callable."),
        BaselineCase("mcp_catalog", "Mock MCP catalog", "mcp", "mock MCP tool appears when configured."),
        BaselineCase("mcp_tool_execution", "Mock MCP execution", "mcp", "mock MCP tool can be selected and executed."),
        BaselineCase("mcp_status", "MCP status", "mcp", "mcp_status reports lifecycle and discovery state."),
        BaselineCase("demo_packaged", "Packaged demo", "demo", "five-minute deterministic demo passes."),
    ]


def run_baseline(
    *,
    output_dir: Path | None = None,
    case_ids: list[str] | None = None,
    save_report: bool = True,
    save_history: bool = False,
) -> BaselineReport:
    """运行基线评测。"""
    requested = set(case_ids or [])
    cases = [case for case in default_cases() if not requested or case.id in requested]
    unknown = sorted(requested - {case.id for case in default_cases()})
    if unknown:
        raise ValueError(f"Unknown baseline case: {unknown[0]}")

    started = time.perf_counter()
    results: list[BaselineCaseResult] = []
    with tempfile.TemporaryDirectory(prefix="codemuse_eval_") as raw:
        run_root = Path(raw)
        for case in cases:
            workspace = run_root / case.id
            workspace.mkdir(parents=True)
            _write_sample_repo(workspace)
            case_started = time.perf_counter()
            failures: list[str] = []
            details: dict[str, object] = {}
            try:
                details = dict(_handler_for_case(case.id)(workspace))
            except AssertionError as exc:
                failures.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive report path
                failures.append(f"{type(exc).__name__}: {exc}")
            results.append(
                BaselineCaseResult(
                    case_id=case.id,
                    name=case.name,
                    category=case.category,
                    passed=not failures,
                    duration_seconds=time.perf_counter() - case_started,
                    failures=failures,
                    metrics=_numeric_metrics(details),
                    details=details,
                )
            )
    report = build_report(results, duration_seconds=time.perf_counter() - started)
    if save_report:
        target_dir = output_dir or (Path.cwd() / "evals" / "reports")
        write_report(report, target_dir, save_history=save_history)
    return report


def run_cli(argv: list[str] | None = None) -> int:
    """运行cli。"""
    parser = argparse.ArgumentParser(description="Run CodeMuse deterministic baseline evals.")
    parser.add_argument("--output", default=str(Path("evals") / "reports"))
    parser.add_argument("--cases", default="", help="Comma-separated case ids. Empty runs all cases.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save-history", action="store_true")
    args = parser.parse_args(argv)

    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    report = run_baseline(output_dir=Path(args.output), case_ids=case_ids, save_history=args.save_history)
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(f"Passed {report.passed}/{report.total_cases} baseline cases.")
        print(f"Report: {Path(args.output) / 'latest.md'}")
    return 0 if report.failed == 0 else 1


def _handler_for_case(case_id: str) -> CaseHandler:
    """处理 handlerfor用例。"""
    handlers: dict[str, CaseHandler] = {
        "file_list": _case_file_list,
        "read_file": _case_read_file,
        "search_text_match": _case_search_text_match,
        "search_text_no_match": _case_search_text_no_match,
        "read_source_file": _case_read_source_file,
        "read_docs_file": _case_read_docs_file,
        "list_ignored_data": _case_list_ignored_data,
        "list_nested_depth": _case_list_nested_depth,
        "write_approval": _case_write_approval,
        "write_reject": _case_write_reject,
        "write_nested_approval": _case_write_nested_approval,
        "write_update_existing_approval": _case_write_update_existing_approval,
        "write_stale_after_target_change": _case_write_stale_after_target_change,
        "replace_approval": _case_replace_approval,
        "replace_reject": _case_replace_reject,
        "replace_all_approval": _case_replace_all_approval,
        "replace_missing_text_blocked": _case_replace_missing_text_blocked,
        "apply_patch_create_approval": _case_apply_patch_create_approval,
        "apply_patch_update_approval": _case_apply_patch_update_approval,
        "apply_patch_reject": _case_apply_patch_reject,
        "apply_patch_stale_after_change": _case_apply_patch_stale_after_change,
        "shell_blocked": _case_shell_blocked,
        "shell_safe_command": _case_shell_safe_command,
        "shell_empty_blocked": _case_shell_empty_blocked,
        "shell_write_risk_preview": _case_shell_write_risk_preview,
        "shell_network_risk_preview": _case_shell_network_risk_preview,
        "checkpoint_rewind": _case_checkpoint_rewind,
        "checkpoint_list_after_create": _case_checkpoint_list_after_create,
        "rewind_restores_nested_file": _case_rewind_restores_nested_file,
        "multiple_checkpoint_rewind": _case_multiple_checkpoint_rewind,
        "project_memory": _case_project_memory,
        "project_memory_recall_context": _case_project_memory_recall_context,
        "project_memory_no_match": _case_project_memory_no_match,
        "save_blueprint_memory": _case_save_blueprint_memory,
        "search_blueprint_memory": _case_search_blueprint_memory,
        "blueprint_analysis": _case_blueprint_analysis,
        "repo_index": _case_repo_index,
        "blueprint_memory_empty_search": _case_blueprint_memory_empty_search,
        "memory_index_pipeline": _case_memory_index_pipeline,
        "subagent": _case_subagent,
        "subagent_read_file": _case_subagent_read_file,
        "subagent_search_text": _case_subagent_search_text,
        "subagent_plan": _case_subagent_plan,
        "web_private_block": _case_web_private_block,
        "web_invalid_url_block": _case_web_invalid_url_block,
        "web_public_preview": _case_web_public_preview,
        "repo_import_plan": _case_repo_import_plan,
        "repo_import_shorthand": _case_repo_import_shorthand,
        "repo_import_ssh": _case_repo_import_ssh,
        "repo_import_branch_nested": _case_repo_import_branch_nested,
        "repo_import_local_ready": _case_repo_import_local_ready,
        "repo_import_local_cache": _case_repo_import_local_cache,
        "repo_git_status": _case_repo_git_status,
        "project_plan": _case_project_plan,
        "project_plan_goal_preserved": _case_project_plan_goal_preserved,
        "web_ui_smoke": _case_web_ui_smoke,
        "web_api_session_list": _case_web_api_session_list,
        "web_api_approval_flow": _case_web_api_approval_flow,
        "web_api_checkpoint_flow": _case_web_api_checkpoint_flow,
        "capability_catalog": _case_capability_catalog,
        "capability_kind_filter_builtin": _case_capability_kind_filter_builtin,
        "skill_runtime_execution": _case_skill_runtime_execution,
        "extension_runtime_execution": _case_extension_runtime_execution,
        "extension_dynamic_tool": _case_extension_dynamic_tool,
        "mcp_catalog": _case_mcp_catalog,
        "mcp_tool_execution": _case_mcp_tool_execution,
        "mcp_status": _case_mcp_status,
        "demo_packaged": _case_demo_packaged,
    }
    return handlers[case_id]


def _case_file_list(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：文件列表。"""
    payload = sdk.run("list files", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "list_files")
    _assert("README.md" in payload["assistant"], "assistant did not include README.md")
    return _details(payload)


def _case_read_file(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：读取文件。"""
    payload = sdk.run("read README.md", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "read_file")
    _assert("Sample Agent" in payload["assistant"], "assistant did not include README content")
    return _details(payload)


def _case_search_text_match(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：搜索文本match。"""
    payload = sdk.run("search ToolRegistry", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "search_text")
    _assert("guide.md" in payload["assistant"] and "ToolRegistry" in payload["assistant"], "search did not include docs guide match")
    return _details(payload)


def _case_search_text_no_match(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：搜索文本nomatch。"""
    payload = sdk.run("search no-such-deterministic-token", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "search_text")
    _assert("No matches" in payload["assistant"], "search did not report no matches")
    return _details(payload)


def _case_read_source_file(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：读取源码文件。"""
    payload = sdk.run("read src/main.py", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "read_file")
    _assert("hello" in payload["assistant"], "assistant did not include source content")
    return _details(payload)


def _case_read_docs_file(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：读取文档文件。"""
    payload = sdk.run("read docs/guide.md", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "read_file")
    _assert("ToolRegistry" in payload["assistant"], "assistant did not include docs content")
    return _details(payload)


def _case_list_ignored_data(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：列表忽略目录数据。"""
    (workspace / ".data" / "secret").mkdir(parents=True)
    (workspace / ".data" / "secret" / "hidden.txt").write_text("hidden", encoding="utf-8")
    payload = sdk.run("list files", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "list_files")
    _assert("hidden.txt" not in payload["assistant"], "list_files exposed .data content")
    return _details(payload)


def _case_list_nested_depth(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：列表嵌套深度。"""
    payload = sdk.run("list files", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "list_files")
    _assert("docs/" in payload["assistant"], "list_files missed docs directory")
    _assert("src/" in payload["assistant"], "list_files missed src directory")
    return _details(payload)


def _case_write_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：写入审批。"""
    target = workspace / "notes" / "eval.txt"
    payload = sdk.run("write file notes/eval.txt content: eval baseline", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "write_file")
    _assert(not target.exists(), "target was written before approval")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "eval baseline\n", "target content was not written after approval")
    _assert_event(approved, "checkpoint_created", "write_file")
    _assert_event(approved, "tool_result", "write_file")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_write_reject(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：写入拒绝。"""
    target = workspace / "notes" / "reject.txt"
    payload = sdk.run("write file notes/reject.txt content: reject me", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "write_file")
    rejected = sdk.reject(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(not target.exists(), "rejected write created target")
    _assert_event(rejected, "approval_rejected", "write_file")
    return {**_details(payload), "rejected_event_count": rejected["event_count"]}


def _case_write_nested_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：写入嵌套审批。"""
    target = workspace / "notes" / "nested" / "eval.txt"
    payload = sdk.run("write file notes/nested/eval.txt content: nested eval", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "write_file")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "nested eval\n", "nested target was not written")
    _assert_event(approved, "tool_result", "write_file")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_write_update_existing_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：写入更新existing审批。"""
    target = workspace / "notes" / "existing.txt"
    target.parent.mkdir()
    target.write_text("before\n", encoding="utf-8")
    payload = sdk.run("write file notes/existing.txt content: after", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "write_file")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "after\n", "existing target was not updated")
    _assert_event(approved, "tool_result", "write_file")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_write_stale_after_target_change(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：写入过期之后target变更。"""
    target = workspace / "notes" / "stale.txt"
    target.parent.mkdir()
    target.write_text("before\n", encoding="utf-8")
    payload = sdk.run("write file notes/stale.txt content: after", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "write_file")
    target.write_text("changed elsewhere\n", encoding="utf-8")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "changed elsewhere\n", "stale write modified target")
    _assert_event(approved, "approval_stale", "write_file")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_replace_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：替换审批。"""
    target = workspace / "README.md"
    payload = sdk.run("replace text README.md old: # Sample Agent new: # Eval Agent", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "replace_text")
    _assert(target.read_text(encoding="utf-8").startswith("# Sample Agent"), "README changed before approval")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8").startswith("# Eval Agent"), "README was not replaced after approval")
    _assert_event(approved, "tool_result", "replace_text")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_replace_reject(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：替换拒绝。"""
    target = workspace / "README.md"
    before = target.read_text(encoding="utf-8")
    payload = sdk.run("replace text README.md old: Sample Agent new: Rejected Agent", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "replace_text")
    rejected = sdk.reject(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == before, "rejected replace changed README")
    _assert_event(rejected, "approval_rejected", "replace_text")
    return {**_details(payload), "rejected_event_count": rejected["event_count"]}


def _case_replace_all_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：替换全部审批。"""
    target = workspace / "docs" / "guide.md"
    payload = sdk.run("replace text docs/guide.md old: alpha new: beta replace_all: true", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "replace_text")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    text = target.read_text(encoding="utf-8")
    _assert("alpha" not in text and text.count("beta") == 2, "replace_all did not replace every match")
    _assert_event(approved, "tool_result", "replace_text")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_replace_missing_text_blocked(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：替换缺失文本阻断。"""
    payload = sdk.run("replace text README.md old: not-present-token new: nope", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "replace_text")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is True, "missing old_text preview was not blocked")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert_event(approved, "approval_stale", "replace_text")
    return {**_details(payload), "blocked": True, "approved_event_count": approved["event_count"]}


def _case_apply_patch_create_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：应用补丁创建审批。"""
    target = workspace / "notes" / "patched.txt"
    payload = sdk.run(f"apply patch patch: {_patch_create_text()}", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "apply_patch")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "patched\n", "apply_patch did not create file")
    _assert_event(approved, "tool_result", "apply_patch")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_apply_patch_update_approval(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：应用补丁更新审批。"""
    target = workspace / "README.md"
    payload = sdk.run(f"apply patch patch: {_patch_update_readme_text()}", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "apply_patch")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert("A tiny deterministic baseline workspace." in target.read_text(encoding="utf-8"), "apply_patch did not update README")
    _assert_event(approved, "tool_result", "apply_patch")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_apply_patch_reject(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：应用补丁拒绝。"""
    target = workspace / "notes" / "patched.txt"
    payload = sdk.run(f"apply patch patch: {_patch_create_text()}", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "apply_patch")
    rejected = sdk.reject(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(not target.exists(), "rejected patch created file")
    _assert_event(rejected, "approval_rejected", "apply_patch")
    return {**_details(payload), "rejected_event_count": rejected["event_count"]}


def _case_apply_patch_stale_after_change(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：应用补丁过期之后变更。"""
    target = workspace / "README.md"
    payload = sdk.run(f"apply patch patch: {_patch_update_readme_text()}", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "apply_patch")
    target.write_text("# Changed before patch\n", encoding="utf-8")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == "# Changed before patch\n", "stale patch modified target")
    _assert_event(approved, "approval_stale", "apply_patch")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_shell_blocked(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Shell阻断。"""
    target = workspace / "README.md"
    payload = sdk.run("run shell command: Remove-Item README.md", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "run_shell")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is True, "shell preview was not blocked")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert(target.exists(), "blocked shell command removed README.md")
    _assert_event(approved, "approval_stale", "run_shell")
    return {**_details(payload), "approved_event_count": approved["event_count"], "blocked": True}


def _case_shell_safe_command(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Shell安全命令。"""
    payload = sdk.run("run shell command: python --version", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "run_shell")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is False, "safe shell preview was blocked")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert_event(approved, "tool_result", "run_shell")
    _assert("Python" in approved["assistant"], "safe shell output did not mention Python")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_shell_empty_blocked(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Shell空命令阻断。"""
    payload = sdk.run("run shell command: ", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "run_shell")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is True, "empty shell command was not blocked")
    return {**_details(payload), "blocked": True}


def _case_shell_write_risk_preview(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Shell写入风险预览。"""
    payload = sdk.run("run shell command: echo hello > notes.txt", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "run_shell")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is False, "write-like shell command should be previewed, not blocked")
    _assert(any("write" in str(reason).lower() for reason in preview["risk_reasons"]), "write risk was not reported")
    return {**_details(payload), "risk_level": str(preview["risk_level"])}


def _case_shell_network_risk_preview(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Shell网络风险预览。"""
    payload = sdk.run("run shell command: curl https://example.com", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "run_shell")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is False, "network-like shell command should be previewed, not blocked")
    _assert(any("network" in str(reason).lower() for reason in preview["risk_reasons"]), "network risk was not reported")
    return {**_details(payload), "risk_level": str(preview["risk_level"])}


def _case_checkpoint_rewind(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：检查点回退。"""
    target = workspace / "README.md"
    checkpoint = sdk.create_checkpoint(workspace, label="baseline checkpoint", collect_events=True)
    checkpoint_id = str(_single_event(checkpoint, "checkpoint_created", None)["details"]["checkpoint_id"])
    before = target.read_text(encoding="utf-8")
    target.write_text("# Changed after checkpoint\n", encoding="utf-8")
    rewind = sdk.rewind(workspace, checkpoint_id, session_id=checkpoint["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == before, "rewind did not restore README.md")
    _assert_event(rewind, "checkpoint_rewound", None)
    return {"checkpoint_id": checkpoint_id, "event_count": rewind["event_count"]}


def _case_checkpoint_list_after_create(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：检查点列表之后创建。"""
    checkpoint = sdk.create_checkpoint(workspace, label="listed checkpoint", collect_events=True)
    checkpoint_id = str(_single_event(checkpoint, "checkpoint_created", None)["details"]["checkpoint_id"])
    listed = sdk.list_checkpoints(workspace, session_id=checkpoint["session_id"])
    ids = {item["checkpoint_id"] for item in listed}
    _assert(checkpoint_id in ids, "created checkpoint was not listed")
    return {"checkpoint_id": checkpoint_id, "checkpoint_count": len(listed)}


def _case_rewind_restores_nested_file(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：回退restores嵌套文件。"""
    target = workspace / "docs" / "guide.md"
    checkpoint = sdk.create_checkpoint(workspace, label="nested checkpoint", collect_events=True)
    checkpoint_id = str(_single_event(checkpoint, "checkpoint_created", None)["details"]["checkpoint_id"])
    before = target.read_text(encoding="utf-8")
    target.write_text("# Mutated docs\n", encoding="utf-8")
    rewind = sdk.rewind(workspace, checkpoint_id, session_id=checkpoint["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8") == before, "rewind did not restore nested file")
    _assert_event(rewind, "checkpoint_rewound", None)
    return {"checkpoint_id": checkpoint_id, "event_count": rewind["event_count"]}


def _case_multiple_checkpoint_rewind(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：multiple检查点回退。"""
    target = workspace / "README.md"
    first = sdk.create_checkpoint(workspace, label="first checkpoint", collect_events=True)
    first_id = str(_single_event(first, "checkpoint_created", None)["details"]["checkpoint_id"])
    target.write_text("# First mutation\n", encoding="utf-8")
    second = sdk.create_checkpoint(workspace, session_id=first["session_id"], label="second checkpoint", collect_events=True)
    target.write_text("# Second mutation\n", encoding="utf-8")
    rewind = sdk.rewind(workspace, first_id, session_id=first["session_id"], collect_events=True)
    _assert(target.read_text(encoding="utf-8").startswith("# Sample Agent"), "rewind did not restore first checkpoint state")
    _assert_event(second, "checkpoint_created", None)
    _assert_event(rewind, "checkpoint_rewound", None)
    return {"checkpoint_id": first_id, "event_count": rewind["event_count"]}


def _case_project_memory(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：项目记忆。"""
    payload = sdk.run("remember this runtime should call tools through ToolRegistry", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "save_project_memory")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert_event(approved, "tool_result", "save_project_memory")
    search = sdk.run("search project memory runtime ToolRegistry", workspace, session_id=payload["session_id"], collect_events=True)
    _assert_event(search, "tool_result", "search_project_memory")
    _assert("ToolRegistry" in search["assistant"], "project memory search did not recall ToolRegistry")
    return {"save_events": approved["event_count"], "search_events": search["event_count"]}


def _case_project_memory_recall_context(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：项目记忆召回上下文。"""
    payload = sdk.run("remember this release gates should use doctor strict mode", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "save_project_memory")
    sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    recall = sdk.run("what did I say about release gates?", workspace, session_id=payload["session_id"], collect_events=True)
    _assert("doctor strict" in recall["assistant"], "memory recall did not inject saved content")
    return {"recall_events": recall["event_count"]}


def _case_project_memory_no_match(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：项目记忆nomatch。"""
    payload = sdk.run("search project memory no-such-memory-token", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "search_project_memory")
    _assert("No generic memory matched" in payload["assistant"], "empty project memory search did not report no matches")
    return _details(payload)


def _case_save_blueprint_memory(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：save蓝图记忆。"""
    payload = sdk.run("save blueprint", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "save_blueprint_memory")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert_event(approved, "tool_result", "save_blueprint_memory")
    _assert("Saved repository blueprint memory" in approved["assistant"], "assistant did not summarize saved blueprint")
    return {**_details(payload), "approved_event_count": approved["event_count"]}


def _case_search_blueprint_memory(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：搜索蓝图记忆。"""
    save = sdk.run("save blueprint", workspace, collect_events=True)
    approval = _single_event(save, "approval_required", "save_blueprint_memory")
    sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=save["session_id"], collect_events=True)
    search = sdk.run("search blueprint architecture", workspace, session_id=save["session_id"], collect_events=True)
    _assert_event(search, "tool_result", "search_blueprint_memory")
    _assert("Minimal architecture" in search["assistant"], "blueprint memory search did not recall architecture chunk")
    return {"save_events": save["event_count"], "search_events": search["event_count"]}


def _case_blueprint_analysis(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：蓝图分析。"""
    payload = sdk.run("analyze repo blueprint", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "analyze_repo_blueprint")
    blueprint = event["details"]["blueprint"]
    _assert("Sample Agent" in blueprint["title"], "blueprint title did not include sample repo")
    _assert(blueprint["modules"], "blueprint modules were empty")
    return {**_details(payload), "module_count": len(blueprint["modules"])}


def _case_repo_index(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库索引。"""
    payload = sdk.run("index repo", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "index_repo_structure")
    repo_index = event["details"]["repo_index"]
    _assert(repo_index["file_count"] >= 4, "repo index file count was too small")
    _assert("README.md" in repo_index["important_files"], "repo index missed README")
    return {**_details(payload), "file_count": repo_index["file_count"]}


def _case_blueprint_memory_empty_search(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：蓝图记忆空命令搜索。"""
    payload = sdk.run("search blueprint no-such-blueprint-token", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "search_blueprint_memory")
    _assert("No blueprint memory matched" in payload["assistant"], "empty blueprint search did not report no matches")
    return _details(payload)


def _case_memory_index_pipeline(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：记忆索引流程。"""
    report = sdk.refresh_memory(workspace)
    result = sdk.search_memory(workspace, "ToolRegistry runtime", limit=3)
    _assert(report["index"]["chunk_count"] >= 1, "memory index did not create chunks")
    _assert(len(result["hits"]) >= 1, "memory pipeline did not return hits")
    _assert("ToolRegistry" in result["markdown"], "memory pipeline did not retrieve workspace content")
    return {
        "chunk_count": report["index"]["chunk_count"],
        "hit_count": len(result["hits"]),
    }


def _case_subagent(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：子 Agent。"""
    payload = sdk.run("use subagent to list files", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "spawn_subagent")
    result = event["details"]["subagent_result"]
    _assert("list_files" in result["used_tools"], "subagent did not use list_files")
    _assert("spawn_subagent" not in result["used_tools"], "subagent recursively used spawn_subagent")
    return _details(payload)


def _case_subagent_read_file(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：子 Agent读取文件。"""
    payload = sdk.run("use subagent to read README.md", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "spawn_subagent")
    result = event["details"]["subagent_result"]
    _assert("read_file" in result["used_tools"], "subagent did not use read_file")
    _assert(len(result["events"]) > 0, "subagent did not return trace events")
    return _details(payload)


def _case_subagent_search_text(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：子 Agent搜索文本。"""
    payload = sdk.run("subagent search ToolRegistry", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "spawn_subagent")
    result = event["details"]["subagent_result"]
    _assert("search_text" in result["used_tools"], "subagent did not use search_text")
    return _details(payload)


def _case_subagent_plan(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：子 Agent计划。"""
    payload = sdk.run("run subagent plan", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "run_subagent_plan")
    result = event["details"]["subagent_plan"]
    _assert(result["task_count"] == 2, "subagent plan did not run both tasks")
    _assert("list_files" in result["used_tools"], "subagent plan did not use list_files")
    return _details(payload)


def _case_web_private_block(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Web私有网络block。"""
    payload = sdk.run("web fetch url: http://127.0.0.1:8000/secret", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "web_fetch")
    _assert(approval["details"]["effect_preview"]["blocked"] is True, "private URL preview was not blocked")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert_event(approved, "approval_stale", "web_fetch")
    _assert_no_event(approved, "tool_result", "web_fetch")
    return {**_details(payload), "approved_event_count": approved["event_count"], "blocked": True}


def _case_web_invalid_url_block(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Web非法URLblock。"""
    payload = sdk.run("web fetch url: not-a-valid-url", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "web_fetch")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is True, "invalid URL preview was not blocked")
    return {**_details(payload), "blocked": True}


def _case_web_public_preview(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Web公网预览。"""
    payload = sdk.run("web fetch url: https://example.com", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "web_fetch")
    preview = approval["details"]["effect_preview"]
    _assert(preview["blocked"] is False, "public URL preview was blocked")
    _assert(preview["hostname"] == "example.com", "public URL hostname was not parsed")
    return {**_details(payload), "risk_level": str(preview["risk_level"])}


def _case_repo_import_plan(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库导入计划。"""
    payload = sdk.run("github import https://github.com/openai/codex/tree/main", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "prepare_repo_import")
    plan = event["details"]["import_plan"]
    _assert(plan["repo_id"] == "openai_codex", "GitHub repo id was not normalized")
    _assert(plan["requires_network"] is True, "GitHub import plan did not require network")
    _assert(plan["import_ready"] is False, "GitHub import plan should not clone in the baseline")
    return {**_details(payload), "repo_id": plan["repo_id"], "requires_network": True}


def _case_repo_import_shorthand(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库导入简写。"""
    payload = sdk.run("github import openai/codex", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "prepare_repo_import")
    plan = event["details"]["import_plan"]
    _assert(plan["repo_id"] == "openai_codex", "shorthand repo id was not normalized")
    _assert(plan["clone_url"] == "https://github.com/openai/codex.git", "shorthand clone URL was wrong")
    return {**_details(payload), "repo_id": plan["repo_id"]}


def _case_repo_import_ssh(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库导入SSH。"""
    payload = sdk.run("github import git@github.com:openai/codex.git", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "prepare_repo_import")
    plan = event["details"]["import_plan"]
    _assert(plan["repo_id"] == "openai_codex", "SSH repo id was not normalized")
    _assert(plan["requires_network"] is True, "SSH import should require network")
    return {**_details(payload), "repo_id": plan["repo_id"]}


def _case_repo_import_branch_nested(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库导入分支嵌套。"""
    payload = sdk.run("github import https://github.com/openai/codex/tree/feature/demo/path", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "prepare_repo_import")
    plan = event["details"]["import_plan"]
    _assert(plan["branch"] == "feature/demo/path", "tree branch path was not preserved")
    return {**_details(payload), "branch": plan["branch"]}


def _case_repo_import_local_ready(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库导入本地就绪。"""
    payload = sdk.run("repo import .", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "prepare_repo_import")
    plan = event["details"]["import_plan"]
    _assert(plan["source_type"] == "local", "local import did not produce local source type")
    _assert(plan["import_ready"] is True, "local import should be ready")
    _assert(plan["requires_network"] is False, "local import should not require network")
    return {**_details(payload), "repo_id": plan["repo_id"]}


def _case_repo_import_local_cache(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库导入本地缓存。"""
    source = workspace / "source_repo"
    source.mkdir()
    _write_sample_repo(source)
    payload = sdk.run("import repository source_repo", workspace, collect_events=True)
    approval = _single_event(payload, "approval_required", "import_repository")
    approved = sdk.approve(workspace, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)
    _assert((workspace / "imports" / "source_repo" / "README.md").exists(), "local import did not copy README")
    _assert_event(approved, "tool_result", "import_repository")
    cache = sdk.run("list repo cache", workspace, collect_events=True)
    _assert_event(cache, "tool_result", "list_repo_cache")
    _assert("source_repo" in cache["assistant"], "repo cache did not list imported repo")
    return {**_details(approved), "cache_event_count": cache["event_count"]}


def _case_repo_git_status(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：仓库Git状态。"""
    payload = sdk.run("repo status", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "repo_git_status")
    git = event["details"]["git"]
    _assert(git["path"], "repo git status did not include path")
    _assert("Repository git status" in payload["assistant"], "assistant did not summarize git status")
    return {**_details(payload), "is_git_repo": str(git["is_git_repo"])}


def _case_project_plan(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：项目计划。"""
    payload = sdk.run("project plan goal: add a safe eval runner", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "build_project_plan")
    plan = event["details"]["plan"]
    task_titles = [task["title"] for task in plan["tasks"]]
    _assert("Project Plan" in payload["assistant"], "assistant did not return project plan heading")
    _assert("Verify and report" in task_titles, "project plan missed verification task")
    _assert(plan["goal"] == "add a safe eval runner", "project plan goal was not preserved")
    return {**_details(payload), "task_count": len(plan["tasks"]), "plan_id": plan["plan_id"]}


def _case_project_plan_goal_preserved(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：项目计划目标保留。"""
    goal = "document strict release gates"
    payload = sdk.run(f"project plan goal: {goal}", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "build_project_plan")
    plan = event["details"]["plan"]
    _assert(plan["goal"] == goal, "project plan did not preserve explicit goal")
    _assert(len(plan["tasks"]) >= 3, "project plan did not create enough tasks")
    return {**_details(payload), "task_count": len(plan["tasks"])}


def _case_web_ui_smoke(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：WebUIsmoke。"""
    manager = WebSessionManager(default_workspace=workspace)
    server = CodeMuseServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        index = _http_text(f"{base}/")
        health = _http_json(f"{base}/api/health")
        capabilities = _http_json(f"{base}/api/capabilities")
        created = _http_json(f"{base}/api/sessions", method="POST", payload={})
        session_id = str(created["session_id"])
        queued = _http_json(f"{base}/api/sessions/{session_id}/prompt", method="POST", payload={"prompt": "list files"})
        handle = manager.get_session(session_id)
        _wait_for_session_event(handle, "prompt_completed")

        _assert("<title>CodeMuse</title>" in index, "web UI index was not served")
        _assert(health["ok"] is True, "api health did not return ok")
        _assert(any(item["name"] == "list_files" for item in capabilities["capabilities"]), "api capabilities missed list_files")
        _assert(queued["session_id"] == session_id, "api prompt did not target the created session")
        return {"capability_count": len(capabilities["capabilities"]), "event_count": len(handle.events_after(0)["events"])}
    finally:
        server.shutdown()
        server.server_close()


def _case_web_api_session_list(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：WebAPI会话列表。"""
    manager = WebSessionManager(default_workspace=workspace)
    server = CodeMuseServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        created = _http_json(f"{base}/api/sessions", method="POST", payload={})
        listed = _http_json(f"{base}/api/sessions")
        ids = {item["session_id"] for item in listed["sessions"]}
        _assert(created["session_id"] in ids, "created session was not listed")
        return {"session_count": len(listed["sessions"])}
    finally:
        server.shutdown()
        server.server_close()


def _case_web_api_approval_flow(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：WebAPI审批流程。"""
    manager = WebSessionManager(default_workspace=workspace)
    server = CodeMuseServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        created = _http_json(f"{base}/api/sessions", method="POST", payload={})
        session_id = str(created["session_id"])
        _http_json(f"{base}/api/sessions/{session_id}/prompt", method="POST", payload={"prompt": "write file notes/api.txt content: via api"})
        handle = manager.get_session(session_id)
        _wait_for_session_event(handle, "approval_required")
        approvals = _http_json(f"{base}/api/sessions/{session_id}/approvals")
        _assert(len(approvals["approvals"]) == 1, "API did not expose pending approval")
        return {"approval_count": len(approvals["approvals"])}
    finally:
        server.shutdown()
        server.server_close()


def _case_web_api_checkpoint_flow(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：WebAPI检查点流程。"""
    manager = WebSessionManager(default_workspace=workspace)
    server = CodeMuseServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        created = _http_json(f"{base}/api/sessions", method="POST", payload={})
        session_id = str(created["session_id"])
        _http_json(f"{base}/api/sessions/{session_id}/checkpoint", method="POST", payload={"label": "api checkpoint"})
        handle = manager.get_session(session_id)
        _wait_for_session_event(handle, "checkpoint_completed")
        checkpoints = _http_json(f"{base}/api/sessions/{session_id}/checkpoints")
        _assert(len(checkpoints["checkpoints"]) == 1, "API did not expose created checkpoint")
        return {"checkpoint_count": len(checkpoints["checkpoints"])}
    finally:
        server.shutdown()
        server.server_close()


def _case_capability_catalog(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：能力目录。"""
    _write_skill(workspace)
    _write_extension(workspace)
    capabilities = sdk.list_capabilities(workspace)
    keys = {(item["kind"], item["name"]) for item in capabilities}
    for key in [
        ("builtin_tool", "list_files"),
        ("builtin_tool", "run_shell"),
        ("web_tool", "web_fetch"),
        ("repo_tool", "prepare_repo_import"),
        ("repo_tool", "import_repository"),
        ("repo_tool", "repo_git_status"),
        ("repo_tool", "list_repo_cache"),
        ("repo_tool", "build_project_plan"),
        ("skill", "run_skill"),
        ("extension", "run_extension"),
        ("skill", "experiment-report"),
        ("extension", "project-extension"),
    ]:
        _assert(key in keys, f"missing capability: {key}")
    by_key = {(item["kind"], item["name"]): item for item in capabilities}
    _assert(
        by_key[("extension", "project-extension")]["metadata"]["execution"] == "manifest_runtime",
        "extension descriptor did not expose manifest runtime",
    )
    return {"capability_count": len(capabilities)}


def _case_capability_kind_filter_builtin(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：能力类型过滤内置。"""
    capabilities = sdk.list_capabilities(workspace, kind="builtin_tool")
    names = {item["name"] for item in capabilities}
    _assert("list_files" in names, "builtin filter missed list_files")
    _assert(all(item["kind"] == "builtin_tool" for item in capabilities), "kind filter returned non-builtin capabilities")
    return {"capability_count": len(capabilities)}


def _case_skill_runtime_execution(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：Skill运行时执行。"""
    _write_skill(workspace)
    payload = sdk.run("run skill name: experiment-report for eval summary", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "run_skill")
    _assert("Skill runtime result" in payload["assistant"], "assistant did not summarize skill runtime result")
    _assert("experiment-report" in payload["assistant"], "skill runtime result missed skill name")
    return _details(payload)


def _case_extension_runtime_execution(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：扩展运行时执行。"""
    _write_extension(workspace)
    payload = sdk.run("run extension name: project-extension with eval input", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "run_extension")
    _assert("Extension runtime result" in payload["assistant"], "assistant did not summarize extension runtime result")
    _assert("project-extension" in payload["assistant"], "extension runtime result missed extension name")
    return _details(payload)


def _case_extension_dynamic_tool(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：扩展动态工具。"""
    _write_extension(workspace)
    payload = sdk.run("extension tool summarize eval input", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "extension__project_extension__summarize")
    _assert("dynamic summary" in payload["assistant"], "dynamic extension tool did not render manifest response")
    return _details(payload)


def _case_mcp_catalog(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：MCP目录。"""
    _write_mcp_config(workspace)
    capabilities = sdk.list_capabilities(workspace, kind="mcp_tool")
    names = {item["name"] for item in capabilities}
    _assert("mcp__demo__echo" in names, "mock MCP tool was not listed")
    return {"mcp_tool_count": len(capabilities)}


def _case_mcp_tool_execution(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：MCP工具执行。"""
    _write_mcp_config(workspace)
    payload = sdk.run("mcp echo hello from eval", workspace, collect_events=True)
    _assert_event(payload, "tool_result", "mcp__demo__echo")
    _assert("mock echo" in payload["assistant"], "mock MCP response was not returned")
    return _details(payload)


def _case_mcp_status(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：MCP状态。"""
    _write_mcp_config(workspace)
    payload = sdk.run("mcp status", workspace, collect_events=True)
    event = _single_event(payload, "tool_result", "mcp_status")
    report = event["details"]["mcp"]
    _assert(report["ready_count"] == 1, "mcp_status did not report ready mock server")
    _assert(report["servers"][0]["tool_count"] == 1, "mcp_status did not report tool count")
    return _details(payload)


def _case_demo_packaged(workspace: Path) -> dict[str, object]:
    """执行 baseline 评测用例：演示打包资源。"""
    report = run_demo(save_report=False)
    _assert(report.failed == 0, "packaged demo failed")
    _assert(report.total_steps == 5, "packaged demo step count changed unexpectedly")
    return {"total_steps": report.total_steps, "passed": report.passed}


def _write_sample_repo(root: Path) -> None:
    """写入sample仓库。"""
    (root / "README.md").write_text(
        "# Sample Agent\n\nA tiny coding agent for deterministic evals.\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text(
        "# Guide\n\nToolRegistry routes tools.\n\nalpha keeps one marker.\nalpha keeps another marker.\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (root / "config.json").write_text('{"name": "sample-agent"}\n', encoding="utf-8")


def _patch_create_text() -> str:
    """处理 补丁创建文本。"""
    return "\n".join(
        [
            "--- /dev/null",
            "+++ b/notes/patched.txt",
            "@@ -0,0 +1 @@",
            "+patched",
        ]
    )


def _patch_update_readme_text() -> str:
    """处理 补丁更新readme文本。"""
    return "\n".join(
        [
            "--- a/README.md",
            "+++ b/README.md",
            "@@ -1,3 +1,3 @@",
            " # Sample Agent",
            " ",
            "-A tiny coding agent for deterministic evals.",
            "+A tiny deterministic baseline workspace.",
        ]
    )


def _write_skill(root: Path) -> None:
    """写入Skill。"""
    skill_dir = root / "skills" / "experiment-report"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: experiment-report\ndescription: Build experiment reports from inputs.\n---\n\n# Body\n",
        encoding="utf-8",
    )


def _write_extension(root: Path) -> None:
    """写入扩展。"""
    extension_dir = root / "extensions" / "project-extension"
    extension_dir.mkdir(parents=True)
    payload = {
        "name": "project-extension",
        "description": "Adds project-specific runtime hooks.",
        "version": "0.1.0",
        "entrypoint": "extension.py",
        "provides": ["tool", "hook"],
        "response_template": "Extension {name} handled {action}: {input}",
        "tools": [
            {
                "name": "summarize",
                "description": "Summarize input through the project extension.",
                "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}},
                "response_template": "dynamic summary from {name}: {input}",
            }
        ],
    }
    (extension_dir / "EXTENSION.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_mcp_config(root: Path) -> None:
    """写入MCPconfig。"""
    payload = {
        "servers": [
            {
                "name": "demo",
                "transport": "mock",
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text from the model.",
                        "response_template": "mock echo: {text}",
                    }
                ],
            }
        ],
    }
    (root / "mcp.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _http_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
    """处理 HTTPJSON。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=3) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise AssertionError("HTTP response was not a JSON object")
    return result


def _http_text(url: str) -> str:
    """处理 HTTP文本。"""
    with urllib.request.urlopen(url, timeout=3) as response:
        return response.read().decode("utf-8")


def _wait_for_session_event(handle, event_type: str, *, timeout: float = 3.0) -> dict[str, object]:
    """等待for会话事件。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = handle.events_after(0)["events"]
        for event in reversed(events):
            if event["type"] == event_type:
                return event
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for event: {event_type}")


def _details(payload: dict[str, object]) -> dict[str, object]:
    """处理 详情。"""
    events = payload.get("events", [])
    tool_names = [
        str(event.get("tool_name"))
        for event in events
        if isinstance(event, dict) and event.get("tool_name")
    ]
    return {
        "event_count": int(payload.get("event_count", 0)),
        "tool_names": sorted(set(tool_names)),
    }


def _single_event(payload: dict[str, object], event_type: str, tool_name: str | None) -> dict[str, object]:
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


def _assert_event(payload: dict[str, object], event_type: str, tool_name: str | None) -> None:
    """断言事件。"""
    for event in payload.get("events", []):
        if not isinstance(event, dict):
            continue
        if event.get("type") == event_type and (tool_name is None or event.get("tool_name") == tool_name):
            return
    raise AssertionError(f"missing event {event_type}[{tool_name}]")


def _assert_no_event(payload: dict[str, object], event_type: str, tool_name: str | None) -> None:
    """断言no事件。"""
    for event in payload.get("events", []):
        if not isinstance(event, dict):
            continue
        if event.get("type") == event_type and (tool_name is None or event.get("tool_name") == tool_name):
            raise AssertionError(f"unexpected event {event_type}[{tool_name}]")


def _assert(condition: bool, message: str) -> None:
    """断言基线评测。"""
    if not condition:
        raise AssertionError(message)


def _numeric_metrics(details: dict[str, object]) -> dict[str, float | int | str]:
    """处理 数值指标。"""
    metrics: dict[str, float | int | str] = {}
    for key, value in details.items():
        if isinstance(value, (int, float, str)):
            metrics[key] = value
    return metrics


if __name__ == "__main__":
    raise SystemExit(run_cli())
