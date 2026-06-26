"""解析 CodeMuse 命令行参数，并将命令分发到 SDK 对应能力。"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from codemuse.api import sdk
from codemuse.benchmarks.baseline import run_baseline
from codemuse.benchmarks.live import compare_providers, write_provider_comparison
from codemuse.benchmarks.report import load_history_entries, write_platform_artifacts
from codemuse.cli.render import parse_json_value, print_events, print_json
from codemuse.demo.runner import run_demo
from codemuse.diagnostics.readiness import run_readiness, write_readiness_report

COMMANDS = {
    "run",
    "sessions",
    "approvals",
    "checkpoint",
    "config",
    "capabilities",
    "timeline",
    "models",
    "memory",
    "benchmark",
    "doctor",
    "demo",
}


def main(argv: list[str] | None = None, *, default_workspace: Path | None = None) -> int:
    """命令行入口，解析参数并返回进程退出码。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = list(sys.argv[1:] if argv is None else argv)
    # 兼容旧脚本用法：没有显式子命令时，仍然按 “直接发送 prompt” 处理。
    if _first_command_token(args) not in COMMANDS:
        return _main_legacy(args, default_workspace=default_workspace)
    return _main_command(args, default_workspace=default_workspace)


def _main_legacy(argv: list[str], *, default_workspace: Path | None) -> int:
    """为该流程的公共逻辑提供局部辅助处理。"""
    parser = argparse.ArgumentParser(description="Run CodeMuse with the configured local LLM provider.")
    parser.add_argument("prompt", nargs="?", help="Prompt to send to the agent.")
    parser.add_argument("--workspace", default=str(_default_workspace(default_workspace)), help="Workspace path for coding tools.")
    parser.add_argument("--session", default=None, help="Existing session id to restore.")
    parser.add_argument("--approve", default=None, help="Approve a pending tool call by approval id.")
    parser.add_argument("--reject", default=None, help="Reject a pending tool call by approval id.")
    parser.add_argument("--list-approvals", action="store_true", help="List pending approvals for the workspace.")
    parser.add_argument("--checkpoint", nargs="?", const="manual checkpoint", help="Create a checkpoint for the current session.")
    parser.add_argument("--list-checkpoints", action="store_true", help="List checkpoints for the workspace or session.")
    parser.add_argument("--rewind", default=None, help="Restore the current session to a checkpoint id.")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    if args.list_approvals:
        _print_approvals(workspace)
        return 0
    if args.list_checkpoints:
        _print_checkpoints(workspace, session_id=args.session)
        return 0
    payload = _run_action(args, workspace)
    print(f"session_id: {payload['session_id']}")
    return 0


def _main_command(argv: list[str], *, default_workspace: Path | None) -> int:
    """为该流程的公共逻辑提供局部辅助处理。"""
    parser = argparse.ArgumentParser(description="CodeMuse command line interface.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_run_parser(subparsers, default_workspace)
    _add_sessions_parser(subparsers, default_workspace)
    _add_approvals_parser(subparsers, default_workspace)
    _add_checkpoint_parser(subparsers, default_workspace)
    _add_config_parser(subparsers, default_workspace)
    _add_capabilities_parser(subparsers, default_workspace)
    _add_timeline_parser(subparsers, default_workspace)
    _add_models_parser(subparsers, default_workspace)
    _add_memory_parser(subparsers, default_workspace)
    _add_benchmark_parser(subparsers, default_workspace)
    _add_doctor_parser(subparsers, default_workspace)
    _add_demo_parser(subparsers, default_workspace)
    args = parser.parse_args(argv)

    if args.command == "run":
        payload = sdk.run(args.prompt, Path(args.workspace).resolve(), session_id=args.session, collect_events=not args.json)
        if args.json:
            print_json(payload)
        else:
            print_events(payload["events"])
            print(f"session_id: {payload['session_id']}")
        return 0
    if args.command == "sessions":
        _handle_sessions(args)
        return 0
    if args.command == "approvals":
        _handle_approvals(args)
        return 0
    if args.command == "checkpoint":
        _handle_checkpoint(args)
        return 0
    if args.command == "config":
        _handle_config(args)
        return 0
    if args.command == "capabilities":
        _handle_capabilities(args)
        return 0
    if args.command == "timeline":
        _handle_timeline(args)
        return 0
    if args.command == "models":
        _handle_models(args)
        return 0
    if args.command == "memory":
        _handle_memory(args)
        return 0
    if args.command == "benchmark":
        return _handle_benchmark(args)
    if args.command == "doctor":
        return _handle_doctor(args)
    if args.command == "demo":
        return _handle_demo(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


def _run_action(args: argparse.Namespace, workspace: Path) -> dict[str, Any]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    if args.approve:
        payload = sdk.approve(workspace, args.approve, session_id=args.session, collect_events=True)
    elif args.reject:
        payload = sdk.reject(workspace, args.reject, session_id=args.session, collect_events=True)
    elif args.checkpoint is not None:
        payload = sdk.create_checkpoint(workspace, session_id=args.session, label=args.checkpoint, collect_events=True)
    elif args.rewind:
        payload = sdk.rewind(workspace, args.rewind, session_id=args.session, collect_events=True)
    else:
        if not args.prompt:
            raise SystemExit("prompt is required unless an approval or checkpoint command is used.")
        payload = sdk.run(args.prompt, workspace, session_id=args.session, collect_events=True)
    print_events(payload["events"])
    return payload


def _handle_sessions(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(args.workspace).resolve()
    if args.sessions_command == "list":
        for session in sdk.list_sessions(workspace):
            print(f"{session['session_id']}  messages={len(session['messages'])}  updated={session['updated_at']}")


def _handle_approvals(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(args.workspace).resolve()
    if args.approvals_command == "list":
        _print_approvals(workspace)
        return
    if args.approvals_command == "approve":
        payload = sdk.approve(workspace, args.approval_id, session_id=args.session, collect_events=True)
    else:
        payload = sdk.reject(workspace, args.approval_id, session_id=args.session, collect_events=True)
    print_events(payload["events"])
    print(f"session_id: {payload['session_id']}")


def _handle_checkpoint(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(args.workspace).resolve()
    if args.checkpoint_command == "list":
        _print_checkpoints(workspace, session_id=args.session)
        return
    if args.checkpoint_command == "create":
        payload = sdk.create_checkpoint(workspace, session_id=args.session, label=args.label, collect_events=True)
    else:
        payload = sdk.rewind(workspace, args.checkpoint_id, session_id=args.session, collect_events=True)
    print_events(payload["events"])
    print(f"session_id: {payload['session_id']}")


def _handle_config(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(args.workspace).resolve()
    if args.config_command == "show":
        print_json(sdk.get_config(workspace))
        return
    value = parse_json_value(args.value)
    if args.config_command == "set":
        print_json(sdk.set_config_path(workspace, args.path, value))
    else:
        print_json(sdk.set_runtime_config_path(workspace, args.path, value))


def _handle_capabilities(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(args.workspace).resolve()
    if args.capabilities_command == "list":
        capabilities = sdk.list_capabilities(workspace, kind=args.kind)
        if args.json:
            print_json(capabilities)
            return
        for item in capabilities:
            print(f"{item['kind']}  {item['name']}  risk={item['risk_level']}  source={item['source']}")
        return
    print_json(sdk.get_capability(workspace, kind=args.kind, name=args.name))


def _handle_timeline(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(args.workspace).resolve()
    events = sdk.list_timeline(workspace, session_id=args.session, limit=args.limit)
    if args.json:
        print_json(events)
        return
    for event in events:
        label = str(event["type"])
        if event.get("tool_name"):
            label += f"[{event['tool_name']}]"
        message = str(event.get("message") or "")
        print(f"{event.get('session_id')}  turn={event.get('turn_id')}  {label}  {message}")


def _handle_models(args: argparse.Namespace) -> None:
    """处理 CLI 子命令并调用对应 SDK 能力。"""
    workspace = Path(getattr(args, "workspace", _default_workspace(None))).resolve()
    providers = sdk.list_provider_readiness(workspace)
    if args.json:
        print_json(providers)
        return
    for item in providers:
        status = "ready" if item["ready"] else ("implemented" if item["implemented"] else "planned")
        reason = f"  {item['reason']}" if item.get("reason") else ""
        print(f"{item['name']}  {status}  model={item['model']}  key={item['api_key_env'] or '-'}{reason}")


def _handle_memory(args: argparse.Namespace) -> None:
    """Inspect or refresh the local memory/RAG pipeline."""
    workspace = Path(args.workspace).resolve()
    if args.memory_command == "index":
        payload = sdk.refresh_memory(workspace, max_files=args.max_files)
        if args.json:
            print_json(payload)
            return
        index = payload["index"]
        print(
            f"Memory index refreshed: files={index['file_count']} "
            f"chunks={index['chunk_count']} path={index['index_path']}"
        )
        return
    payload = sdk.search_memory(workspace, args.query, limit=args.limit)
    if args.json:
        print_json(payload)
        return
    print(payload["markdown"])


def _handle_benchmark(args: argparse.Namespace) -> int:
    """Run deterministic benchmark/eval suites from the CLI."""
    if args.benchmark_command == "history":
        output = Path(args.output)
        artifacts = write_platform_artifacts(output)
        entries = load_history_entries(output)
        if args.json:
            print_json([asdict(item) for item in entries])
            return 0
        print(f"Benchmark history: {len(entries)} run(s).")
        for item in entries[-args.limit :]:
            print(
                f"{item.run_id}  cases={item.total_cases}  pass={item.passed}/{item.total_cases}  "
                f"success={item.success_rate:.2%}  duration={item.duration_seconds:.3f}s"
            )
        print(f"Index: {artifacts['index_md']}")
        print(f"Trend: {artifacts['trend_svg']}")
        return 0
    if args.benchmark_command == "providers":
        providers = [item.strip() for item in args.providers.split(",") if item.strip()]
        report = compare_providers(providers=providers or None, prompt=args.prompt, probe=args.probe)
        output_paths = write_provider_comparison(report, Path(args.output))
        if args.json:
            print_json(asdict(report))
            return 0
        print(f"Provider comparison: {report.ready_providers}/{report.total_providers} ready.")
        for item in report.results:
            print(f"{item.provider}  {item.status}  ready={item.ready}  model={item.model}  {item.error}")
        print(f"Report: {output_paths[1]}")
        return 0

    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    report = run_baseline(
        output_dir=Path(args.output),
        case_ids=case_ids,
        save_history=args.save_history,
    )
    if args.json:
        print_json(asdict(report))
    else:
        print(f"Passed {report.passed}/{report.total_cases} baseline cases.")
        print(f"Report: {Path(args.output) / 'latest.md'}")
    return 0 if report.failed == 0 else 1


def _handle_doctor(args: argparse.Namespace) -> int:
    """Run release-readiness checks."""
    workspace = Path(args.workspace).resolve()
    eval_output = Path(args.eval_output).resolve() if args.eval_output else None
    report = run_readiness(
        workspace,
        run_eval=args.run_eval,
        eval_output=eval_output,
        run_compile=args.run_compile,
        run_tests=args.run_tests,
        web_smoke=args.web_smoke,
        demo_smoke=args.demo_smoke,
        strict=args.strict,
    )
    output_paths: tuple[Path, Path] | None = None
    if args.output:
        output_paths = write_readiness_report(report, Path(args.output))
    if args.json:
        print_json(asdict(report))
    else:
        print(
            f"CodeMuse Doctor: {report.status.upper()} "
            f"({report.passed} pass, {report.warnings} warn, {report.failed} fail, "
            f"release_ready={report.release_ready})"
        )
        for check in report.checks:
            print(f"{check.status.upper()}  {check.category}/{check.id}  {check.message}")
        if output_paths is not None:
            print(f"Report: {output_paths[1]}")
    return 0 if report.release_ready else 1


def _handle_demo(args: argparse.Namespace) -> int:
    """Run packaged demo flows."""
    report = run_demo(output_dir=Path(args.output), save_report=not args.no_report)
    if args.json:
        print_json(asdict(report))
    else:
        print(f"CodeMuse Demo: passed {report.passed}/{report.total_steps} steps.")
        for step in report.steps:
            status = "PASS" if step.passed else "FAIL"
            print(f"{status}  {step.id}  {step.summary}")
        if not args.no_report:
            print(f"Report: {Path(args.output) / 'latest.md'}")
    return 0 if report.failed == 0 else 1


def _print_approvals(workspace: Path) -> None:
    """将查询结果格式化打印到 CLI。"""
    for approval in sdk.list_approvals(workspace, status="pending"):
        print(
            f"{approval['approval_id']}  session={approval['session_id']}  "
            f"tool={approval['tool_name']}  reason={approval['reason']}"
        )


def _print_checkpoints(workspace: Path, *, session_id: str | None) -> None:
    """将查询结果格式化打印到 CLI。"""
    for checkpoint in sdk.list_checkpoints(workspace, session_id=session_id):
        print(
            f"{checkpoint['checkpoint_id']}  session={checkpoint['session_id']}  "
            f"turn={checkpoint['turn_id']}  messages={len(checkpoint['messages'])}  label={checkpoint['label']}"
        )


def _add_workspace(parser: argparse.ArgumentParser, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser.add_argument("--workspace", "-w", default=str(_default_workspace(default_workspace)))


def _add_run_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("run", help="Send a prompt to CodeMuse.")
    parser.add_argument("prompt")
    _add_workspace(parser, default_workspace)
    parser.add_argument("--session", default=None)
    parser.add_argument("--json", action="store_true")


def _add_sessions_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("sessions", help="Manage sessions.")
    nested = parser.add_subparsers(dest="sessions_command", required=True)
    list_parser = nested.add_parser("list")
    _add_workspace(list_parser, default_workspace)


def _add_approvals_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("approvals", help="Manage pending approvals.")
    nested = parser.add_subparsers(dest="approvals_command", required=True)
    list_parser = nested.add_parser("list")
    _add_workspace(list_parser, default_workspace)
    for name in ["approve", "reject"]:
        command = nested.add_parser(name)
        command.add_argument("approval_id")
        command.add_argument("--session", default=None)
        _add_workspace(command, default_workspace)


def _add_checkpoint_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("checkpoint", help="Manage checkpoints.")
    nested = parser.add_subparsers(dest="checkpoint_command", required=True)
    list_parser = nested.add_parser("list")
    list_parser.add_argument("--session", default=None)
    _add_workspace(list_parser, default_workspace)
    create_parser = nested.add_parser("create")
    create_parser.add_argument("--session", default=None)
    create_parser.add_argument("--label", default="manual checkpoint")
    _add_workspace(create_parser, default_workspace)
    rewind_parser = nested.add_parser("rewind")
    rewind_parser.add_argument("checkpoint_id")
    rewind_parser.add_argument("--session", default=None)
    _add_workspace(rewind_parser, default_workspace)


def _add_config_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("config", help="Inspect or update config.")
    nested = parser.add_subparsers(dest="config_command", required=True)
    show_parser = nested.add_parser("show")
    _add_workspace(show_parser, default_workspace)
    for name in ["set", "runtime-set"]:
        command = nested.add_parser(name)
        command.add_argument("path")
        command.add_argument("value")
        _add_workspace(command, default_workspace)


def _add_capabilities_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("capabilities", help="Inspect discoverable capabilities.")
    nested = parser.add_subparsers(dest="capabilities_command", required=True)
    list_parser = nested.add_parser("list")
    list_parser.add_argument("--kind", default=None)
    list_parser.add_argument("--json", action="store_true")
    _add_workspace(list_parser, default_workspace)
    show_parser = nested.add_parser("show")
    show_parser.add_argument("kind")
    show_parser.add_argument("name")
    _add_workspace(show_parser, default_workspace)


def _add_timeline_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("timeline", help="Inspect persisted runtime events.")
    nested = parser.add_subparsers(dest="timeline_command", required=True)
    show_parser = nested.add_parser("show")
    show_parser.add_argument("--session", default=None)
    show_parser.add_argument("--limit", type=int, default=30)
    show_parser.add_argument("--json", action="store_true")
    _add_workspace(show_parser, default_workspace)


def _add_models_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """为 CLI 子命令注册 argparse 参数。"""
    parser = subparsers.add_parser("models", help="Inspect model provider options.")
    nested = parser.add_subparsers(dest="models_command", required=True)
    providers_parser = nested.add_parser("providers")
    providers_parser.add_argument("--json", action="store_true")
    _add_workspace(providers_parser, default_workspace)


def _add_memory_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    parser = subparsers.add_parser("memory", help="Index and search local memory/RAG context.")
    nested = parser.add_subparsers(dest="memory_command", required=True)
    index_parser = nested.add_parser("index")
    index_parser.add_argument("--max-files", type=int, default=300)
    index_parser.add_argument("--json", action="store_true")
    _add_workspace(index_parser, default_workspace)
    search_parser = nested.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=6)
    search_parser.add_argument("--json", action="store_true")
    _add_workspace(search_parser, default_workspace)


def _add_benchmark_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """Register benchmark/eval commands."""
    parser = subparsers.add_parser("benchmark", help="Run deterministic baseline evals.")
    nested = parser.add_subparsers(dest="benchmark_command", required=True)
    run_parser = nested.add_parser("run")
    run_parser.add_argument("--output", default=str(_default_workspace(default_workspace) / "evals" / "reports"))
    run_parser.add_argument("--cases", default="", help="Comma-separated case ids. Empty runs all cases.")
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--save-history", action="store_true")
    history_parser = nested.add_parser("history")
    history_parser.add_argument("--output", default=str(_default_workspace(default_workspace) / "evals" / "reports"))
    history_parser.add_argument("--json", action="store_true")
    history_parser.add_argument("--limit", type=int, default=10)
    providers_parser = nested.add_parser("providers")
    providers_parser.add_argument("--output", default=str(_default_workspace(default_workspace) / "evals" / "reports"))
    providers_parser.add_argument("--providers", default="", help="Comma-separated providers. Empty checks all.")
    providers_parser.add_argument("--prompt", default="Reply with: CodeMuse live provider ready.")
    providers_parser.add_argument("--probe", action="store_true", help="Actually call ready live providers.")
    providers_parser.add_argument("--json", action="store_true")


def _add_doctor_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """Register release-readiness doctor command."""
    parser = subparsers.add_parser("doctor", help="Run release-readiness checks.")
    _add_workspace(parser, default_workspace)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Write readiness.json and readiness.md to this directory.")
    parser.add_argument("--run-eval", action="store_true", help="Run a fresh deterministic baseline eval.")
    parser.add_argument("--eval-output", default="", help="Directory for baseline eval reports when --run-eval is used.")
    parser.add_argument("--run-compile", action="store_true", help="Run python -m compileall for src and tests.")
    parser.add_argument("--run-tests", action="store_true", help="Run the full unittest suite.")
    parser.add_argument("--web-smoke", action="store_true", help="Start a local server and smoke-test the packaged Web UI/API.")
    parser.add_argument("--demo-smoke", action="store_true", help="Run the packaged deterministic demo.")
    parser.add_argument("--strict", action="store_true", help="Run all release gates and return non-zero for warnings.")


def _add_demo_parser(subparsers: argparse._SubParsersAction, default_workspace: Path | None) -> None:
    """Register packaged demo commands."""
    parser = subparsers.add_parser("demo", help="Run packaged CodeMuse demos.")
    nested = parser.add_subparsers(dest="demo_command", required=True)
    run_parser = nested.add_parser("run")
    run_parser.add_argument("--output", default=str(_default_workspace(default_workspace) / "artifacts" / "demo"))
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--no-report", action="store_true")


def _first_command_token(argv: list[str]) -> str | None:
    """为该流程的公共逻辑提供局部辅助处理。"""
    skip_next = False
    options_with_values = {"--workspace", "-w", "--session", "--approve", "--reject", "--rewind"}
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token in options_with_values:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return token
    return None


def _default_workspace(default_workspace: Path | None) -> Path:
    """为该流程的公共逻辑提供局部辅助处理。"""
    return (default_workspace or Path.cwd()).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
