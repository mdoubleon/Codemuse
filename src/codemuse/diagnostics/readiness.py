"""Build release-readiness reports for the local CodeMuse workspace."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from codemuse.api import sdk
from codemuse.benchmarks.baseline import run_baseline
from codemuse.demo.runner import run_demo
from codemuse.server.http import CodeMuseServer
from codemuse.server.session_manager import WebSessionManager

CheckStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class ReadinessCheck:
    """One doctor check result."""

    id: str
    category: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReleaseReadinessReport:
    """Structured release-readiness report."""

    generated_at: str
    workspace: str
    strict: bool
    release_ready: bool
    status: CheckStatus
    passed: int
    warnings: int
    failed: int
    checks: list[ReadinessCheck]


def run_readiness(
    workspace: Path,
    *,
    run_eval: bool = False,
    eval_output: Path | None = None,
    run_compile: bool = False,
    run_tests: bool = False,
    web_smoke: bool = False,
    demo_smoke: bool = False,
    strict: bool = False,
) -> ReleaseReadinessReport:
    """Run local doctor checks and return a release-readiness report."""
    root = workspace.resolve()
    if strict:
        run_eval = True
        run_compile = True
        run_tests = True
        web_smoke = True
        demo_smoke = True
    checks: list[ReadinessCheck] = []
    checks.extend(_environment_checks())
    checks.extend(_project_file_checks(root))
    checks.extend(_capability_checks(root))
    checks.extend(_model_provider_checks(root))
    checks.append(_memory_pipeline_check(root))
    checks.append(_compile_check(root, run_compile=run_compile))
    checks.append(_unittest_check(root, run_tests=run_tests))
    checks.append(_web_smoke_check(root, web_smoke=web_smoke))
    checks.append(_demo_smoke_check(demo_smoke=demo_smoke))
    checks.append(_eval_report_check(root, run_eval=run_eval, eval_output=eval_output))
    checks.append(_benchmark_platform_check(root, eval_output=eval_output))

    failed = sum(1 for item in checks if item.status == "fail")
    warnings = sum(1 for item in checks if item.status == "warn")
    passed = sum(1 for item in checks if item.status == "pass")
    status: CheckStatus = "fail" if failed else ("warn" if warnings else "pass")
    release_ready = failed == 0 and (not strict or warnings == 0)
    return ReleaseReadinessReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        workspace=str(root),
        strict=strict,
        release_ready=release_ready,
        status=status,
        passed=passed,
        warnings=warnings,
        failed=failed,
        checks=checks,
    )


def write_readiness_report(report: ReleaseReadinessReport, output_dir: Path) -> tuple[Path, Path]:
    """Persist release-readiness JSON and Markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "readiness.json"
    md_path = output_dir / "readiness.md"
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: ReleaseReadinessReport) -> str:
    """Render a human-readable release-readiness report."""
    lines = [
        "# CodeMuse Release Readiness",
        "",
        f"- Generated at: `{report.generated_at}`",
        f"- Workspace: `{report.workspace}`",
        f"- Strict: `{report.strict}`",
        f"- Status: `{report.status.upper()}`",
        f"- Release ready: `{report.release_ready}`",
        f"- Pass / warn / fail: `{report.passed}` / `{report.warnings}` / `{report.failed}`",
        "",
        "## Checks",
        "",
        "| Check | Category | Status | Message |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        lines.append(f"| `{check.id}` | `{check.category}` | {check.status.upper()} | {check.message} |")
    lines.append("")
    return "\n".join(lines)


def _environment_checks() -> list[ReadinessCheck]:
    version = sys.version_info
    ok = version >= (3, 10)
    return [
        ReadinessCheck(
            id="python.version",
            category="environment",
            status="pass" if ok else "fail",
            message=f"Python {platform.python_version()} detected.",
            details={"required": ">=3.10", "executable": sys.executable},
        )
    ]


def _project_file_checks(root: Path) -> list[ReadinessCheck]:
    required_files = [
        "README.md",
        "PROJECT_GUIDE.md",
        "pyproject.toml",
        ".env.example",
        "docs/source-map.md",
        "docs/demo.md",
        "docs/safety.md",
        "docs/interview-narrative.md",
        "docs/known-limitations.md",
        "src/codemuse/app/bootstrap.py",
        "src/codemuse/runtime/runtime.py",
        "src/codemuse/tools/registry.py",
        "src/codemuse/memory/retrieval_hook.py",
        "src/codemuse/web/static/index.html",
        "src/codemuse/web/static/app.js",
        "src/codemuse/web/static/styles.css",
    ]
    missing = [item for item in required_files if not (root / item).exists()]
    checks = [
        ReadinessCheck(
            id="project.required_files",
            category="project",
            status="fail" if missing else "pass",
            message="Required project docs, runtime files, and static Web files are present."
            if not missing
            else f"Missing required files: {', '.join(missing)}.",
            details={"missing": missing, "required_count": len(required_files)},
        )
    ]
    checks.extend(_module_file_checks(root))
    return checks


def _module_file_checks(root: Path) -> list[ReadinessCheck]:
    module_files = [
        "src/codemuse/runtime/runtime.py",
        "src/codemuse/tools/registry.py",
        "src/codemuse/storage/checkpoints.py",
        "src/codemuse/mcp/manager.py",
        "src/codemuse/subagents/manager.py",
        "src/codemuse/skills/loader.py",
        "src/codemuse/extensions/loader.py",
        "src/codemuse/web_tools/guarded_fetch.py",
        "src/codemuse/benchmarks/baseline.py",
        "src/codemuse/demo/runner.py",
        "src/codemuse/memory/index_pipeline.py",
        "src/codemuse/memory/retrieval.py",
        "src/codemuse/memory/file_memory_vector.py",
    ]
    missing = [item for item in module_files if not (root / item).exists()]
    return [
        ReadinessCheck(
            id="project.core_modules",
            category="project",
            status="fail" if missing else "pass",
            message="Core runtime, safety, extension, and eval modules are present."
            if not missing
            else f"Missing core modules: {', '.join(missing)}.",
            details={"missing": missing, "required_count": len(module_files)},
        )
    ]


def _capability_checks(root: Path) -> list[ReadinessCheck]:
    try:
        capabilities = sdk.list_capabilities(root)
    except Exception as exc:  # pragma: no cover - defensive doctor path
        return [
            ReadinessCheck(
                id="capabilities.catalog",
                category="capabilities",
                status="fail",
                message=f"Capability catalog failed to load: {type(exc).__name__}: {exc}",
            )
        ]

    keys = {(str(item["kind"]), str(item["name"])) for item in capabilities}
    required = {
        ("builtin_tool", "list_files"),
        ("builtin_tool", "read_file"),
        ("builtin_tool", "write_file"),
        ("builtin_tool", "replace_text"),
        ("builtin_tool", "apply_patch"),
        ("builtin_tool", "run_shell"),
        ("repo_tool", "prepare_repo_import"),
        ("repo_tool", "import_repository"),
        ("repo_tool", "repo_git_status"),
        ("repo_tool", "list_repo_cache"),
        ("repo_tool", "build_project_plan"),
        ("repo_tool", "save_blueprint_memory"),
        ("subagent_tool", "spawn_subagent"),
        ("subagent_tool", "run_subagent_plan"),
        ("web_tool", "web_fetch"),
        ("mcp_tool", "mcp_status"),
        ("skill", "run_skill"),
        ("extension", "run_extension"),
    }
    missing = sorted(required - keys)
    kinds = sorted({str(item["kind"]) for item in capabilities})
    required_runtime_tools = {("skill", "run_skill"), ("extension", "run_extension")}
    missing_runtime_tools = sorted(required_runtime_tools - keys)
    runtime_tools = sorted(key for key in keys if key in required_runtime_tools)
    return [
        ReadinessCheck(
            id="capabilities.core_catalog",
            category="capabilities",
            status="fail" if missing else "pass",
            message="Core coding-agent capabilities are discoverable."
            if not missing
            else f"Missing required capabilities: {_format_pairs(missing)}.",
            details={"capability_count": len(capabilities), "missing": missing},
        ),
        ReadinessCheck(
            id="capabilities.extension_runtime",
            category="capabilities",
            status="fail" if missing_runtime_tools else "pass",
            message="Skill and extension runtime tools are registered."
            if not missing_runtime_tools
            else "Skill and extension runtime tools must be registered before UI/provider surfaces rely on them.",
            details={"loaded_kinds": kinds, "runtime_tools": runtime_tools, "missing": missing_runtime_tools},
        ),
    ]


def _model_provider_checks(root: Path) -> list[ReadinessCheck]:
    providers = sdk.list_provider_readiness(root)
    fake = next((item for item in providers if item["name"] == "fake"), None)
    live_not_implemented = [str(item["name"]) for item in providers if item["name"] != "fake" and not item["implemented"]]
    live_not_ready = [str(item["name"]) for item in providers if item["name"] != "fake" and item["implemented"] and not item["ready"]]
    return [
        ReadinessCheck(
            id="models.fake_provider",
            category="models",
            status="pass" if fake and fake["implemented"] else "fail",
            message="Deterministic FakeLLM provider is implemented."
            if fake and fake["implemented"]
            else "Deterministic FakeLLM provider is not implemented.",
            details={"providers": providers},
        ),
        ReadinessCheck(
            id="models.live_providers",
            category="models",
            status="fail" if live_not_implemented else "pass",
            message=f"Live provider implementations still missing: {', '.join(live_not_implemented)}."
            if live_not_implemented
            else "Live provider implementations are available.",
            details={"missing": live_not_implemented},
        ),
        ReadinessCheck(
            id="models.live_provider_keys",
            category="models",
            status="warn" if live_not_ready else "pass",
            message=f"Live provider API keys are not configured: {', '.join(live_not_ready)}."
            if live_not_ready
            else "Live provider API keys are configured.",
            details={"not_ready": live_not_ready, "providers": providers},
        ),
    ]


def _memory_pipeline_check(root: Path) -> ReadinessCheck:
    try:
        with tempfile.TemporaryDirectory(prefix="codemuse_doctor_memory_") as raw:
            sample = Path(raw)
            _write_sample_repo(sample)
            report = sdk.refresh_memory(sample)
            result = sdk.search_memory(sample, "Sample Agent hello", limit=3)
    except Exception as exc:  # pragma: no cover - defensive doctor path
        return ReadinessCheck(
            id="memory.rag_pipeline",
            category="memory",
            status="fail",
            message=f"Memory/RAG pipeline failed: {type(exc).__name__}: {exc}",
        )
    ok = int(report["index"]["chunk_count"]) > 0 and len(result["hits"]) > 0
    return ReadinessCheck(
        id="memory.rag_pipeline",
        category="memory",
        status="pass" if ok else "fail",
        message="Hybrid memory index and retrieval pipeline is operational."
        if ok
        else "Hybrid memory index and retrieval pipeline returned no usable context.",
        details={"index": report["index"], "hit_count": len(result["hits"])},
    )


def _compile_check(root: Path, *, run_compile: bool) -> ReadinessCheck:
    if not run_compile:
        return ReadinessCheck(
            id="quality.compileall",
            category="quality",
            status="warn",
            message="compileall was not run in this doctor invocation. Use --run-compile or --strict.",
            details={"fresh_run": False},
        )
    result = _run_subprocess(root, [sys.executable, "-m", "compileall", "-q", "src", "tests"])
    return ReadinessCheck(
        id="quality.compileall",
        category="quality",
        status="pass" if result["returncode"] == 0 else "fail",
        message="Source and tests compile successfully."
        if result["returncode"] == 0
        else "compileall failed for source or tests.",
        details=result,
    )


def _unittest_check(root: Path, *, run_tests: bool) -> ReadinessCheck:
    if not run_tests:
        return ReadinessCheck(
            id="quality.unittest",
            category="quality",
            status="warn",
            message="unittest discovery was not run in this doctor invocation. Use --run-tests or --strict.",
            details={"fresh_run": False},
        )
    result = _run_subprocess(root, [sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    return ReadinessCheck(
        id="quality.unittest",
        category="quality",
        status="pass" if result["returncode"] == 0 else "fail",
        message="Full unittest suite passed." if result["returncode"] == 0 else "Full unittest suite failed.",
        details=result,
    )


def _web_smoke_check(root: Path, *, web_smoke: bool) -> ReadinessCheck:
    if not web_smoke:
        return ReadinessCheck(
            id="web.api_smoke",
            category="web",
            status="warn",
            message="Web/API smoke was not run in this doctor invocation. Use --web-smoke or --strict.",
            details={"fresh_run": False},
        )
    with tempfile.TemporaryDirectory(prefix="codemuse_doctor_web_") as raw:
        sample = Path(raw)
        _write_sample_repo(sample)
        manager = WebSessionManager(default_workspace=sample)
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

            assertions = [
                ("index_title", "<title>CodeMuse</title>" in index),
                ("health_ok", health.get("ok") is True),
                ("capability_list_files", any(item.get("name") == "list_files" for item in capabilities.get("capabilities", []))),
                ("prompt_session", queued.get("session_id") == session_id),
            ]
            failed = [name for name, ok in assertions if not ok]
            return ReadinessCheck(
                id="web.api_smoke",
                category="web",
                status="fail" if failed else "pass",
                message="Packaged Web UI and /api session loop smoke passed."
                if not failed
                else f"Web/API smoke assertions failed: {', '.join(failed)}.",
                details={
                    "fresh_run": True,
                    "base_url": base,
                    "capability_count": len(capabilities.get("capabilities", [])),
                    "event_count": len(handle.events_after(0)["events"]),
                    "failed_assertions": failed,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive doctor path
            return ReadinessCheck(
                id="web.api_smoke",
                category="web",
                status="fail",
                message=f"Web/API smoke failed: {type(exc).__name__}: {exc}",
                details={"fresh_run": True},
            )
        finally:
            server.shutdown()
            server.server_close()


def _demo_smoke_check(*, demo_smoke: bool) -> ReadinessCheck:
    if not demo_smoke:
        return ReadinessCheck(
            id="demo.packaged",
            category="demo",
            status="warn",
            message="Packaged demo was not run in this doctor invocation. Use --demo-smoke or --strict.",
            details={"fresh_run": False},
        )
    report = run_demo(save_report=False)
    return ReadinessCheck(
        id="demo.packaged",
        category="demo",
        status="pass" if report.failed == 0 else "fail",
        message=f"Packaged demo passed {report.passed}/{report.total_steps} steps.",
        details={
            "fresh_run": True,
            "total_steps": report.total_steps,
            "passed": report.passed,
            "failed": report.failed,
        },
    )


def _eval_report_check(root: Path, *, run_eval: bool, eval_output: Path | None) -> ReadinessCheck:
    output = (eval_output or (root / "evals" / "reports")).resolve()
    if run_eval:
        try:
            report = run_baseline(output_dir=output)
        except Exception as exc:  # pragma: no cover - defensive doctor path
            return ReadinessCheck(
                id="eval.baseline",
                category="eval",
                status="fail",
                message=f"Baseline eval failed to run: {type(exc).__name__}: {exc}",
                details={"output": str(output), "fresh_run": True},
            )
        status: CheckStatus = "pass" if report.failed == 0 else "fail"
        return ReadinessCheck(
            id="eval.baseline",
            category="eval",
            status=status,
            message=f"Fresh baseline eval passed {report.passed}/{report.total_cases} cases.",
            details={"output": str(output), "fresh_run": True, "failed": report.failed, "total_cases": report.total_cases},
        )

    latest = output / "latest.json"
    if not latest.exists():
        return ReadinessCheck(
            id="eval.baseline",
            category="eval",
            status="warn",
            message="No baseline eval report found. Run `codemuse benchmark run` or `codemuse doctor --run-eval` before publishing a release artifact.",
            details={"expected": str(latest), "fresh_run": False},
        )
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ReadinessCheck(
            id="eval.baseline",
            category="eval",
            status="fail",
            message=f"Baseline eval report is not valid JSON: {exc}",
            details={"expected": str(latest), "fresh_run": False},
        )
    failed = int(payload.get("failed", 0))
    total = int(payload.get("total_cases", 0))
    status = "pass" if failed == 0 and total >= 60 else "fail"
    return ReadinessCheck(
        id="eval.baseline",
        category="eval",
        status=status,
        message=f"Latest baseline eval report has {total - failed}/{total} passing cases.",
        details={"report": str(latest), "fresh_run": False, "failed": failed, "total_cases": total},
    )


def _benchmark_platform_check(root: Path, *, eval_output: Path | None) -> ReadinessCheck:
    output = (eval_output or (root / "evals" / "reports")).resolve()
    latest = output / "latest.json"
    required = [
        output / "index.json",
        output / "index.md",
        output / "trend.json",
        output / "trend.svg",
        output / "failures.json",
    ]
    missing = [path.name for path in required if not path.exists()]
    if not latest.exists():
        return ReadinessCheck(
            id="benchmark.platform",
            category="eval",
            status="warn",
            message="Benchmark platform artifacts are not generated yet.",
            details={"output": str(output), "missing": ["latest.json", *missing]},
        )
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ReadinessCheck(
            id="benchmark.platform",
            category="eval",
            status="fail",
            message=f"Benchmark latest.json is invalid: {exc}",
            details={"output": str(output)},
        )
    missing_fields = [field for field in ["proxy_metrics", "failure_summary"] if field not in payload]
    status: CheckStatus = "fail" if missing or missing_fields else "pass"
    message = (
        "Benchmark index, trend, SVG chart, proxy metrics, and failure taxonomy are present."
        if status == "pass"
        else "Benchmark platform artifacts are incomplete."
    )
    return ReadinessCheck(
        id="benchmark.platform",
        category="eval",
        status=status,
        message=message,
        details={"output": str(output), "missing_artifacts": missing, "missing_fields": missing_fields},
    )


def _format_pairs(items: list[tuple[str, str]]) -> str:
    return ", ".join(f"{kind}:{name}" for kind, name in items)


def _run_subprocess(root: Path, command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    env = dict(os.environ)
    src_path = str(root / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_path if not existing else src_path + os.pathsep + existing
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return {
        "fresh_run": True,
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }


def _tail(text: str, *, limit: int = 2000) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean
    return clean[-limit:]


def _write_sample_repo(root: Path) -> None:
    (root / "README.md").write_text("# Sample Agent\n\nA tiny project.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")


def _http_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
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
    with urllib.request.urlopen(url, timeout=3) as response:
        return response.read().decode("utf-8")


def _wait_for_session_event(handle, event_type: str, *, timeout: float = 3.0) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = handle.events_after(0)["events"]
        for event in reversed(events):
            if event["type"] == event_type:
                return event
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for event: {event_type}")
