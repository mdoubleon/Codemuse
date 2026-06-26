"""Live provider readiness and optional probe benchmark."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codemuse.config.schema import ModelConfig
from codemuse.domain.messages import ChatMessage
from codemuse.llm.registry import PROVIDERS, create_llm_provider, provider_readiness


@dataclass(frozen=True)
class ProviderComparisonResult:
    provider: str
    model: str
    implemented: bool
    ready: bool
    status: str
    duration_seconds: float = 0.0
    text_preview: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderComparisonReport:
    generated_at: str
    prompt: str
    probed: bool
    total_providers: int
    ready_providers: int
    results: list[ProviderComparisonResult]


def compare_providers(
    *,
    providers: list[str] | None = None,
    prompt: str = "Reply with: CodeMuse live provider ready.",
    probe: bool = False,
) -> ProviderComparisonReport:
    """Compare live provider readiness, optionally making a real provider call."""
    requested = providers or ["fake", "openai_compatible", "bailian"]
    readiness = {item["name"]: item for item in provider_readiness()}
    results: list[ProviderComparisonResult] = []
    for provider in requested:
        info = readiness.get(provider)
        if info is None:
            results.append(
                ProviderComparisonResult(
                    provider=provider,
                    model="",
                    implemented=False,
                    ready=False,
                    status="unknown",
                    error=f"Unknown provider: {provider}",
                )
            )
            continue
        if not info["implemented"]:
            results.append(_result_from_readiness(info, status="not_implemented"))
            continue
        if provider != "fake" and not info["ready"]:
            results.append(_result_from_readiness(info, status="missing_api_key"))
            continue
        if not probe:
            results.append(_result_from_readiness(info, status="ready" if info["ready"] else "available"))
            continue
        results.append(_probe_provider(provider, str(info["model"]), prompt))
    return ProviderComparisonReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        prompt=prompt,
        probed=probe,
        total_providers=len(results),
        ready_providers=sum(1 for item in results if item.ready),
        results=results,
    )


def write_provider_comparison(report: ProviderComparisonReport, output_dir: Path) -> tuple[Path, Path]:
    """Persist provider comparison JSON and Markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "providers.json"
    md_path = output_dir / "providers.md"
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_provider_comparison_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_provider_comparison_markdown(report: ProviderComparisonReport) -> str:
    lines = [
        "# CodeMuse Provider Comparison",
        "",
        f"- Generated at: `{report.generated_at}`",
        f"- Probe mode: `{report.probed}`",
        f"- Ready providers: `{report.ready_providers}` / `{report.total_providers}`",
        "",
        "| Provider | Model | Ready | Status | Duration | Usage | Error |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for item in report.results:
        usage = ", ".join(f"{key}={value}" for key, value in item.usage.items()) or "-"
        error = item.error or "-"
        lines.append(
            f"| `{item.provider}` | `{item.model}` | {item.ready} | `{item.status}` | "
            f"{item.duration_seconds:.3f}s | {usage} | {error} |"
        )
    lines.append("")
    return "\n".join(lines)


def _result_from_readiness(info: dict[str, object], *, status: str) -> ProviderComparisonResult:
    return ProviderComparisonResult(
        provider=str(info["name"]),
        model=str(info.get("model") or ""),
        implemented=bool(info.get("implemented")),
        ready=bool(info.get("ready")),
        status=status,
        error=str(info.get("reason") or ""),
        metadata=dict(info),
    )


def _probe_provider(provider: str, model: str, prompt: str) -> ProviderComparisonResult:
    descriptor = PROVIDERS[provider]
    config = ModelConfig(
        provider=provider,
        model=model or descriptor.default_model,
        base_url=descriptor.default_base_url,
        api_key_env=descriptor.default_api_key_env,
    )
    llm = create_llm_provider(config)
    started = time.perf_counter()
    try:
        response = llm.complete([ChatMessage.text("user", prompt)], tools=[])
    except Exception as exc:  # noqa: BLE001 - live boundary reports provider errors
        return ProviderComparisonResult(
            provider=provider,
            model=model,
            implemented=True,
            ready=False,
            status="probe_failed",
            duration_seconds=time.perf_counter() - started,
            error=f"{type(exc).__name__}: {exc}",
        )
    return ProviderComparisonResult(
        provider=provider,
        model=model,
        implemented=True,
        ready=True,
        status="probed",
        duration_seconds=time.perf_counter() - started,
        text_preview=response.text[:500],
        usage=response.usage,
        metadata=response.provider_metadata,
    )

