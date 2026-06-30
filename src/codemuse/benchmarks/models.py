"""Data models for deterministic CodeMuse baseline evaluations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BaselineCase:
    """定义 BaselineCase的结构化数据。"""
    id: str
    name: str
    category: str
    description: str


@dataclass(frozen=True)
class BaselineCaseResult:
    """保存 BaselineCase 结果的结构化数据。"""
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
    """保存 Baseline 报告的结构化数据。"""
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
    """定义 BenchmarkHistoryEntry的结构化数据。"""
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
