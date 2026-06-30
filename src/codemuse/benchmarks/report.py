"""Build and persist benchmark reports for deterministic eval runs."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from codemuse.benchmarks.models import BaselineCaseResult, BaselineReport, BenchmarkHistoryEntry

TOKEN_PROXY_PER_CASE = 24
TOKEN_PROXY_PER_EVENT = 16
TOKEN_PROXY_PER_TOOL = 32
COST_PROXY_USD_PER_1K_TOKENS = 0.002


def build_report(
    results: list[BaselineCaseResult],
    *,
    suite: str = "baseline-deterministic",
    duration_seconds: float = 0.0,
) -> BaselineReport:
    """构建报告。"""
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    failed = total - passed
    return BaselineReport(
        suite=suite,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_cases=total,
        passed=passed,
        failed=failed,
        success_rate=(passed / total) if total else 0.0,
        duration_seconds=duration_seconds,
        category_summary=_category_summary(results),
        proxy_metrics=_proxy_metrics(results, duration_seconds=duration_seconds),
        failure_summary=_failure_summary(results),
        results=results,
    )


def write_report(report: BaselineReport, output_dir: Path, *, save_history: bool = False) -> tuple[Path, Path]:
    """写入报告。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    md_path = output_dir / "latest.md"
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    if save_history:
        run_id = _run_id(report)
        history_dir = output_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_json = history_dir / f"{run_id}.json"
        history_md = history_dir / f"{run_id}.md"
        history_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        history_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        # Keep the Stage 28 stamped-file shape for backwards compatibility.
        legacy_json = output_dir / f"{run_id}.json"
        legacy_md = output_dir / f"{run_id}.md"
        legacy_json.write_text(history_json.read_text(encoding="utf-8"), encoding="utf-8")
        legacy_md.write_text(history_md.read_text(encoding="utf-8"), encoding="utf-8")
    write_platform_artifacts(output_dir)
    return json_path, md_path


def write_platform_artifacts(output_dir: Path) -> dict[str, Path]:
    """Build benchmark index, trend, SVG chart, and failure taxonomy artifacts."""
    entries = load_history_entries(output_dir)
    if not entries:
        latest = output_dir / "latest.json"
        if latest.exists():
            report = _load_report(latest)
            entries = [_history_entry(report, latest, output_dir / "latest.md")]
    entries = sorted(entries, key=lambda item: item.generated_at)
    index_json = output_dir / "index.json"
    index_md = output_dir / "index.md"
    trend_json = output_dir / "trend.json"
    trend_svg = output_dir / "trend.svg"
    failures_json = output_dir / "failures.json"
    index_json.write_text(json.dumps([asdict(item) for item in entries], ensure_ascii=False, indent=2), encoding="utf-8")
    index_md.write_text(render_history_markdown(entries), encoding="utf-8")
    trend_payload = _trend_payload(entries)
    trend_json.write_text(json.dumps(trend_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    trend_svg.write_text(render_trend_svg(entries), encoding="utf-8")
    failures_json.write_text(json.dumps(_failure_taxonomy_from_history(output_dir), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "index_json": index_json,
        "index_md": index_md,
        "trend_json": trend_json,
        "trend_svg": trend_svg,
        "failures_json": failures_json,
    }


def render_markdown(report: BaselineReport) -> str:
    """渲染Markdown。"""
    lines = [
        "# CodeMuse Baseline Eval Report",
        "",
        f"- Suite: `{report.suite}`",
        f"- Generated at: `{report.generated_at}`",
        f"- Total cases: `{report.total_cases}`",
        f"- Pass / fail: `{report.passed}` / `{report.failed}`",
        f"- Success rate: `{report.success_rate:.2%}`",
        f"- Duration: `{report.duration_seconds:.3f}s`",
        f"- Estimated tokens: `{int(report.proxy_metrics.get('estimated_tokens', 0))}`",
        f"- Estimated cost: `${float(report.proxy_metrics.get('estimated_cost_usd', 0.0)):.6f}`",
        "",
        "## Category Summary",
        "",
        "| Category | Total | Passed | Success rate | Avg duration |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for category, item in sorted(report.category_summary.items()):
        lines.append(
            f"| `{category}` | {item['total']} | {item['passed']} | "
            f"{float(item['success_rate']):.2%} | {float(item['average_duration']):.3f}s |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Category | Status | Failures |",
            "| --- | --- | --- | --- |",
        ]
    )
    for result in report.results:
        failures = "; ".join(result.failures) or "-"
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"| `{result.case_id}` | `{result.category}` | {status} | {failures} |")
    lines.extend(
        [
            "",
            "## Failure Summary",
            "",
            "| Category | Count |",
            "| --- | ---: |",
        ]
    )
    for category, item in sorted(report.failure_summary.items()):
        lines.append(f"| `{category}` | {item['count']} |")
    lines.extend(
        [
            "",
            "## Proxy Metrics",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
    )
    for key, value in sorted(report.proxy_metrics.items()):
        lines.append(f"| `{key}` | {value} |")
    lines.append("")
    return "\n".join(lines)


def render_history_markdown(entries: list[BenchmarkHistoryEntry]) -> str:
    """渲染历史Markdown。"""
    lines = [
        "# CodeMuse Benchmark History",
        "",
        "| Run | Generated | Cases | Pass/fail | Success | Duration | Tokens | Cost |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in entries:
        lines.append(
            f"| `{item.run_id}` | `{item.generated_at}` | {item.total_cases} | "
            f"{item.passed}/{item.failed} | {item.success_rate:.2%} | "
            f"{item.duration_seconds:.3f}s | {item.estimated_tokens} | ${item.estimated_cost_usd:.6f} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_trend_svg(entries: list[BenchmarkHistoryEntry]) -> str:
    """渲染趋势SVG。"""
    width = 720
    height = 260
    pad = 36
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    if not entries:
        points = [(pad, pad + plot_h)]
    elif len(entries) == 1:
        y = pad + plot_h * (1 - entries[0].success_rate)
        points = [(pad + plot_w / 2, y)]
    else:
        points = []
        for index, item in enumerate(entries):
            x = pad + (plot_w * index / (len(entries) - 1))
            y = pad + plot_h * (1 - item.success_rate)
            points.append((x, y))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    circles = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"><title>{entries[i].run_id if i < len(entries) else ""}</title></circle>'
        for i, (x, y) in enumerate(points)
    )
    latest = entries[-1] if entries else None
    latest_text = f"{latest.success_rate:.2%} success, {latest.duration_seconds:.3f}s" if latest else "no runs"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="#ffffff"/>
  <text x="{pad}" y="24" font-family="Arial, sans-serif" font-size="16" fill="#111827">CodeMuse Benchmark Trend</text>
  <text x="{width - pad}" y="24" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#374151">{latest_text}</text>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{pad + plot_h}" stroke="#9ca3af"/>
  <line x1="{pad}" y1="{pad + plot_h}" x2="{pad + plot_w}" y2="{pad + plot_h}" stroke="#9ca3af"/>
  <text x="8" y="{pad + 4}" font-family="Arial, sans-serif" font-size="11" fill="#6b7280">100%</text>
  <text x="14" y="{pad + plot_h}" font-family="Arial, sans-serif" font-size="11" fill="#6b7280">0%</text>
  <polyline fill="none" stroke="#2563eb" stroke-width="3" points="{polyline}"/>
  <g fill="#16a34a" stroke="#ffffff" stroke-width="1.5">
    {circles}
  </g>
</svg>
"""


def _category_summary(results: list[BaselineCaseResult]) -> dict[str, dict[str, float | int]]:
    """处理 categorysummary。"""
    grouped: dict[str, list[BaselineCaseResult]] = {}
    for item in results:
        grouped.setdefault(item.category, []).append(item)
    summary: dict[str, dict[str, float | int]] = {}
    for category, items in grouped.items():
        total = len(items)
        passed = sum(1 for item in items if item.passed)
        durations = [item.duration_seconds for item in items]
        summary[category] = {
            "total": total,
            "passed": passed,
            "success_rate": (passed / total) if total else 0.0,
            "average_duration": (sum(durations) / len(durations)) if durations else 0.0,
        }
    return summary


def load_history_entries(output_dir: Path) -> list[BenchmarkHistoryEntry]:
    """加载历史entries。"""
    history_dir = output_dir / "history"
    entries: list[BenchmarkHistoryEntry] = []
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.json")):
            report = _load_report(path)
            entries.append(_history_entry(report, path, path.with_suffix(".md")))
    return entries


def _history_entry(report: BaselineReport, json_path: Path, md_path: Path) -> BenchmarkHistoryEntry:
    """处理 历史条目。"""
    average = report.duration_seconds / report.total_cases if report.total_cases else 0.0
    return BenchmarkHistoryEntry(
        run_id=_run_id(report),
        suite=report.suite,
        generated_at=report.generated_at,
        total_cases=report.total_cases,
        passed=report.passed,
        failed=report.failed,
        success_rate=report.success_rate,
        duration_seconds=report.duration_seconds,
        average_case_duration=average,
        estimated_tokens=int(report.proxy_metrics.get("estimated_tokens", 0)),
        estimated_cost_usd=float(report.proxy_metrics.get("estimated_cost_usd", 0.0)),
        report_json=json_path.as_posix(),
        report_markdown=md_path.as_posix(),
    )


def _load_report(path: Path) -> BaselineReport:
    """加载报告。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = [
        BaselineCaseResult(
            case_id=item["case_id"],
            name=item["name"],
            category=item["category"],
            passed=bool(item["passed"]),
            duration_seconds=float(item["duration_seconds"]),
            failures=list(item.get("failures") or []),
            metrics=dict(item.get("metrics") or {}),
            details=dict(item.get("details") or {}),
        )
        for item in payload["results"]
    ]
    return BaselineReport(
        suite=payload["suite"],
        generated_at=payload["generated_at"],
        total_cases=int(payload["total_cases"]),
        passed=int(payload["passed"]),
        failed=int(payload["failed"]),
        success_rate=float(payload["success_rate"]),
        duration_seconds=float(payload["duration_seconds"]),
        category_summary=dict(payload.get("category_summary") or {}),
        proxy_metrics=dict(payload.get("proxy_metrics") or _proxy_metrics(results, duration_seconds=float(payload["duration_seconds"]))),
        failure_summary=dict(payload.get("failure_summary") or _failure_summary(results)),
        results=results,
    )


def _run_id(report: BaselineReport) -> str:
    """运行ID。"""
    clean = report.generated_at.replace(":", "").replace("-", "").replace("+", "z")
    clean = clean.replace(".", "-")
    return f"{report.suite}-{clean}"


def _proxy_metrics(results: list[BaselineCaseResult], *, duration_seconds: float) -> dict[str, float | int | str]:
    """处理 proxy指标。"""
    event_count = 0
    tool_count = 0
    for result in results:
        raw_events = result.details.get("event_count", 0)
        if isinstance(raw_events, int):
            event_count += raw_events
        raw_tools = result.details.get("tool_names", [])
        if isinstance(raw_tools, list):
            tool_count += len(raw_tools)
    estimated_tokens = (
        len(results) * TOKEN_PROXY_PER_CASE
        + event_count * TOKEN_PROXY_PER_EVENT
        + tool_count * TOKEN_PROXY_PER_TOOL
    )
    return {
        "estimated_tokens": estimated_tokens,
        "estimated_cost_usd": round((estimated_tokens / 1000) * COST_PROXY_USD_PER_1K_TOKENS, 6),
        "duration_seconds": round(duration_seconds, 3),
        "average_case_duration": round(duration_seconds / len(results), 6) if results else 0.0,
        "event_count_proxy": event_count,
        "tool_count_proxy": tool_count,
        "cost_model": f"${COST_PROXY_USD_PER_1K_TOKENS:.3f}/1k proxy tokens",
    }


def _failure_summary(results: list[BaselineCaseResult]) -> dict[str, dict[str, int]]:
    """处理 失败summary。"""
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        for failure in result.failures:
            category = _classify_failure(failure)
            item = summary.setdefault(category, {"count": 0})
            item["count"] += 1
    if not summary:
        summary["none"] = {"count": 0}
    return summary


def _classify_failure(message: str) -> str:
    """处理 classify失败。"""
    lowered = message.lower()
    if "approval" in lowered or "stale" in lowered or "reject" in lowered:
        return "approval"
    if "timeout" in lowered:
        return "timeout"
    if "web" in lowered or "http" in lowered or "url" in lowered:
        return "web"
    if "mcp" in lowered:
        return "mcp"
    if "keyerror" in lowered or "typeerror" in lowered or "valueerror" in lowered:
        return "exception"
    if "missing event" in lowered:
        return "event"
    return "assertion"


def _trend_payload(entries: list[BenchmarkHistoryEntry]) -> dict[str, object]:
    """处理 趋势载荷。"""
    if not entries:
        return {"runs": [], "delta": {}}
    first = entries[0]
    latest = entries[-1]
    return {
        "runs": [asdict(item) for item in entries],
        "delta": {
            "success_rate": latest.success_rate - first.success_rate,
            "duration_seconds": latest.duration_seconds - first.duration_seconds,
            "estimated_tokens": latest.estimated_tokens - first.estimated_tokens,
            "estimated_cost_usd": round(latest.estimated_cost_usd - first.estimated_cost_usd, 6),
        },
        "latest": asdict(latest),
    }


def _failure_taxonomy_from_history(output_dir: Path) -> dict[str, object]:
    """处理 失败分类from历史。"""
    latest_path = output_dir / "latest.json"
    reports = []
    if latest_path.exists():
        reports.append(_load_report(latest_path))
    history_dir = output_dir / "history"
    if history_dir.exists():
        reports.extend(_load_report(path) for path in sorted(history_dir.glob("*.json")))
    totals: dict[str, int] = {}
    failing_cases: dict[str, int] = {}
    for report in reports:
        for category, item in report.failure_summary.items():
            totals[category] = totals.get(category, 0) + int(item.get("count", 0))
        for result in report.results:
            if result.failures:
                failing_cases[result.case_id] = failing_cases.get(result.case_id, 0) + 1
    return {
        "taxonomy": totals or {"none": 0},
        "failing_cases": failing_cases,
        "report_count": len(reports),
    }
