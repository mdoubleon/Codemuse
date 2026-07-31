"""Bounded workflow orchestration for explicit multi-agent requests."""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from codemuse.subagents.blackboard import AgentManifest, Blackboard
from codemuse.subagents.manager import SubAgentManager
from codemuse.subagents.task_graph import TaskGraph, TaskNode
from codemuse.subagents.worktree import WorktreeManager, WorktreeUnavailable


def workflow_nodes(workflow: str, *, allow_edits: bool = False) -> list[TaskNode]:
    if workflow == "debug":
        return [
            TaskNode("memory", "memory-scout", "Find relevant remembered context."),
            TaskNode("tests", "repo-researcher", "Inspect tests and likely failure causes."),
            TaskNode("review", "change-reviewer", "Review current changes and risks."),
        ]
    if workflow == "code_change":
        nodes = [
            TaskNode("memory", "memory-scout", "Find relevant remembered context."),
            TaskNode("repo", "repo-researcher", "Inspect implementation paths."),
            TaskNode("api", "api-scout", "Trace interfaces and call sites."),
            TaskNode("plan", "implementation-planner", "Turn research into a minimal plan.", ["memory", "repo", "api"]),
        ]
        if allow_edits:
            nodes.extend(
                [
                    TaskNode("patch", "code-worker", "Prepare scoped edits in an isolated worktree.", ["plan"], allow_edits=True),
                    TaskNode("review", "change-reviewer", "Review the staged result.", ["patch"]),
                ]
            )
        else:
            nodes.append(TaskNode("review", "change-reviewer", "Review the implementation plan and risks.", ["plan"]))
        return nodes
    return [
        TaskNode("memory", "memory-scout", "Find relevant remembered context."),
        TaskNode("repo", "repo-researcher", "Inspect relevant repository paths."),
        TaskNode("api", "api-scout", "Trace interfaces and call sites."),
    ]


class SubAgentOrchestrator:
    def __init__(self, manager: SubAgentManager) -> None:
        self.manager = manager
        self.workspace = manager.workspace

    def run(self, *, goal: str, workflow: str = "research", max_agents: int = 4, allow_edits: bool = False) -> dict[str, Any]:
        workflow = workflow if workflow in {"research", "debug", "code_change"} else "research"
        self.manager.cancellation_token.reset()
        graph = TaskGraph(workflow_nodes(workflow, allow_edits=allow_edits))
        blackboard = Blackboard()
        run_id = uuid.uuid4().hex[:12]
        steps: list[dict[str, Any]] = []
        max_workers = max(1, min(int(max_agents or 1), 4))
        for batch in graph.batches():
            runnable = [
                node for node in batch
                if all((blackboard.get(dep) is None or blackboard.get(dep).status == "completed") for dep in node.depends_on)
            ]
            if not runnable:
                break

            def execute(node: TaskNode) -> tuple[TaskNode, dict[str, Any]]:
                context = blackboard.dependency_context(node.depends_on)
                task = f"Goal: {goal}\nRole: {node.objective}\nDependency reports: {context}"
                review_artifact = _dependency_artifact(context) if node.node_id == "review" else None
                if review_artifact is not None:
                    patch_text = Path(str(review_artifact["patch_path"])).read_text(encoding="utf-8", errors="replace")
                    task += (
                        "\nReview the actual staged patch and changed files. Report regressions, missing tests, and risks."
                        "\nFinish with exactly one decision line: `REVIEW_DECISION: approved` or "
                        "`REVIEW_DECISION: rejected`. Only the exact approved decision can release the artifact; "
                        "a missing or malformed decision is treated as rejected."
                        f"\nPatch artifact metadata: {json.dumps(review_artifact, ensure_ascii=False)}"
                        f"\nPatch:\n{patch_text[:20000]}"
                    )
                started = time.time()
                attempts = 2 if node.node_id == "patch" and node.allow_edits else 1
                last_error = ""
                for attempt in range(1, attempts + 1):
                    if self.manager.cancellation_token.is_cancelled:
                        return node, {"node_id": node.node_id, "spec_name": node.agent, "status": "cancelled", "summary": "orchestration cancelled", "attempt": attempt}
                    try:
                        if node.node_id == "patch" and node.allow_edits:
                            worktrees = WorktreeManager(self.workspace)
                            handle = worktrees.create(run_id=run_id, agent=f"{node.agent}-{attempt}")
                            result = self.manager.run_sync(spec_name=node.agent, task=task, tool_workspace=Path(handle.worktree_path))
                            artifact = worktrees.finalize(handle)
                            payload = result.to_dict()
                            payload["artifact"] = artifact.to_dict() if artifact else None
                            if artifact is None:
                                raise RuntimeError("code-worker completed without producing a worktree diff")
                        else:
                            review_workspace = Path(str(review_artifact["worktree_path"])) if review_artifact is not None else None
                            result = self.manager.run_sync(spec_name=node.agent, task=task, tool_workspace=review_workspace)
                            payload = result.to_dict()
                            if review_artifact is not None:
                                worktrees = WorktreeManager(self.workspace)
                                artifact = worktrees.load_artifact(str(review_artifact["artifact_id"]))
                                decision = _review_decision(result.summary)
                                approved = (
                                    result.status == "completed"
                                    and decision == "approved"
                                    and worktrees.apply_check(artifact)
                                )
                                worktrees.record_review(artifact, approved=approved, summary=result.summary)
                                payload["review"] = {
                                    "artifact_id": artifact.artifact_id,
                                    "approved": approved,
                                    "decision": decision or "missing",
                                    "summary": result.summary,
                                }
                                if not approved:
                                    payload["status"] = "failed"
                        payload.update({"node_id": node.node_id, "attempt": attempt, "duration_ms": int((time.time() - started) * 1000)})
                        return node, payload
                    except Exception as exc:  # noqa: BLE001
                        last_error = str(exc)
                return node, {"node_id": node.node_id, "spec_name": node.agent, "status": "failed", "summary": last_error, "error": last_error, "attempt": attempts}

            if len(runnable) > 1:
                with ThreadPoolExecutor(max_workers=min(max_workers, len(runnable)), thread_name_prefix="codemuse-orchestration") as executor:
                    results = list(executor.map(execute, runnable))
            else:
                results = [execute(runnable[0])]
            for node, payload in results:
                status = "completed" if payload.get("status") == "completed" else "failed"
                graph.mark(node.node_id, "completed" if status == "completed" else "failed")
                artifact_payload = payload.get("artifact")
                manifest = AgentManifest(
                    node.agent,
                    status,
                    str(payload.get("summary") or ""),
                    findings=list(payload.get("findings") or []),
                    artifacts=[dict(artifact_payload)] if isinstance(artifact_payload, dict) else [],
                )
                blackboard.put(node.node_id, manifest)
                steps.append(payload)
        artifact_info = next((step.get("artifact") for step in steps if step.get("artifact")), None)
        success = bool(steps) and all(step.get("status") == "completed" for step in steps)
        return {
            "run_id": run_id,
            "goal": goal,
            "workflow": workflow,
            "success": success,
            "parallel": max_workers > 1 and any(len(batch) > 1 for batch in graph.batches()),
            "max_concurrency": max_workers,
            "execution_mode": "isolated_worktree" if workflow == "code_change" and allow_edits else "read_only",
            "steps": steps,
            "blackboard": blackboard.to_dict(),
            "artifact": artifact_info,
            "summary": "\n".join(str(step.get("summary") or "") for step in steps[-2:]),
        }


def _dependency_artifact(context: list[dict[str, Any]]) -> dict[str, Any] | None:
    for dependency in context:
        artifacts = dependency.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict) and artifact.get("artifact_id"):
                    return artifact
    return None


def _review_decision(summary: str) -> str | None:
    """Accept one explicit, machine-checkable reviewer decision and fail closed."""
    decisions = [
        line
        for line in str(summary).splitlines()
        if line.startswith("REVIEW_DECISION:")
    ]
    if decisions == ["REVIEW_DECISION: approved"]:
        return "approved"
    if decisions == ["REVIEW_DECISION: rejected"]:
        return "rejected"
    return None


__all__ = ["SubAgentOrchestrator", "workflow_nodes"]
