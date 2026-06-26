"""Build project plans from repository blueprints."""
from __future__ import annotations

import hashlib
from itertools import count

from codemuse.domain.blueprint import RepoBlueprint
from codemuse.domain.project_plan import ProjectPlan, ProjectPlanTask


def build_project_plan_from_blueprint(blueprint: RepoBlueprint, *, goal: str) -> ProjectPlan:
    clean_goal = goal.strip() or "Understand and evolve this repository safely."
    task_counter = count(1)
    tasks: list[ProjectPlanTask] = []

    tasks.append(
        _task(
            task_counter,
            "Confirm product goal and constraints",
            "discovery",
            "Read the README, package/config files, and key entrypoints to confirm the intended user workflow.",
            _first_paths(blueprint.key_files, 6),
            acceptance=[
                "Goal is written in one paragraph.",
                "Known constraints and risky areas are listed.",
            ],
        )
    )
    tasks.append(
        _task(
            task_counter,
            "Map architecture boundaries",
            "discovery",
            "Use the blueprint module map to identify which layer should own each requested change.",
            [module.path for module in blueprint.modules[:8]],
            depends_on=["T01"],
            acceptance=[
                "Each planned change maps to one module boundary.",
                "No unrelated top-level architecture is introduced.",
            ],
        )
    )

    for module in blueprint.modules[:3]:
        tasks.append(
            _task(
                task_counter,
                f"Plan change inside {module.path}",
                "implementation",
                f"Design the smallest implementation step for `{module.path}` based on its role: {module.role}",
                module.signals[:6] or [module.path],
                depends_on=["T02"],
                acceptance=[
                    "Implementation scope is limited to this module boundary.",
                    "Required tests or smoke checks are named.",
                ],
            )
        )

    tasks.append(
        _task(
            task_counter,
            "Persist reusable learning",
            "memory",
            "Save or refresh blueprint memory so future planning can recall the architectural decisions.",
            _first_paths(blueprint.key_files, 8),
            depends_on=[tasks[-1].task_id if tasks else "T02"],
            acceptance=[
                "Blueprint memory search can find the new decision.",
                "Memory text is concise and reusable.",
            ],
        )
    )
    tasks.append(
        _task(
            task_counter,
            "Verify and report",
            "verification",
            "Run focused tests, baseline evals, and document the final plan/result.",
            [path for path in blueprint.key_files if "test" in path.lower()][:6],
            depends_on=[tasks[-1].task_id],
            acceptance=[
                "Relevant unit tests or baseline cases pass.",
                "Docs or handoff notes describe what changed.",
            ],
        )
    )

    plan_id = _stable_id(blueprint.blueprint_id, clean_goal, ",".join(task.task_id for task in tasks))
    return ProjectPlan(
        plan_id=plan_id,
        goal=clean_goal,
        blueprint_id=blueprint.blueprint_id,
        repo_id=blueprint.repo_id,
        title=f"{blueprint.title}: Project Plan",
        summary=f"Plan for `{clean_goal}` using blueprint `{blueprint.blueprint_id}`.",
        tasks=tasks,
        risks=_risks(blueprint),
        verification=_verification_steps(blueprint),
    )


def format_project_plan(plan: ProjectPlan) -> str:
    lines = [
        f"# Project Plan: {plan.title}",
        "",
        f"- plan_id: {plan.plan_id}",
        f"- goal: {plan.goal}",
        f"- blueprint_id: {plan.blueprint_id}",
        f"- repo_id: {plan.repo_id}",
        "",
        "## Summary",
        plan.summary,
        "",
        "## Tasks",
    ]
    for task in plan.tasks:
        lines.append(f"### {task.task_id}: {task.title}")
        lines.append(f"- phase: {task.phase}")
        if task.depends_on:
            lines.append("- depends_on: " + ", ".join(task.depends_on))
        if task.source_paths:
            lines.append("- source_paths: " + ", ".join(task.source_paths[:8]))
        lines.append("")
        lines.append(task.description)
        if task.acceptance:
            lines.append("")
            lines.append("Acceptance:")
            lines.extend(f"- {item}" for item in task.acceptance)
        lines.append("")
    lines.append("## Risks")
    lines.extend(f"- {item}" for item in (plan.risks or ["No major risks detected."]))
    lines.append("")
    lines.append("## Verification")
    lines.extend(f"- {item}" for item in plan.verification)
    return "\n".join(lines).strip()


def _task(
    task_counter,
    title: str,
    phase: str,
    description: str,
    source_paths: list[str],
    *,
    depends_on: list[str] | None = None,
    acceptance: list[str] | None = None,
) -> ProjectPlanTask:
    task_id = f"T{next(task_counter):02d}"
    return ProjectPlanTask(
        task_id=task_id,
        title=title,
        phase=phase,
        description=description,
        source_paths=source_paths,
        depends_on=list(depends_on or []),
        acceptance=list(acceptance or []),
    )


def _risks(blueprint: RepoBlueprint) -> list[str]:
    risks = [
        "Blueprint-derived plans are heuristic; confirm module ownership before editing.",
        "High-risk tools still require approval and checkpoint protection before changes land.",
    ]
    if not blueprint.modules:
        risks.append("No clear module map was detected, so planning confidence is lower.")
    if not blueprint.key_files:
        risks.append("No key files were detected; inspect the repository manually before implementation.")
    return risks


def _verification_steps(blueprint: RepoBlueprint) -> list[str]:
    steps = ["Run focused unit tests for changed modules.", "Run `python scripts\\run_eval.py --output evals\\reports` after cross-layer changes."]
    if blueprint.key_files:
        steps.append("Re-run blueprint analysis and compare key files if architecture changed.")
    return steps


def _first_paths(values: list[str], limit: int) -> list[str]:
    return [value for value in values if value][:limit]


def _stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
