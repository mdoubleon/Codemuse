"""Data models for deterministic CodeMuse baseline evaluations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BaselineCase:
    id: str
    name: str
    category: str
    description: str


@dataclass(frozen=True)
class BaselineCaseResult:
    case_id: str
    name: str
    category: str
    passed: bool
    duration_seconds: float
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BaselineReport:
    suite: str
    generated_at: str
    total_cases: int
    passed: int
    failed: int
    success_rate: float
    duration_seconds: float
    category_summary: dict[str, dict[str, float | int]]
    proxy_metrics: dict[str, float | int | str]
    failure_summary: dict[str, dict[str, int]]
    results: list[BaselineCaseResult]


@dataclass(frozen=True)
class BenchmarkHistoryEntry:
    run_id: str
    suite: str
    generated_at: str
    total_cases: int
    passed: int
    failed: int
    success_rate: float
    duration_seconds: float
    average_case_duration: float
    estimated_tokens: int
    estimated_cost_usd: float
    report_json: str
    report_markdown: str
