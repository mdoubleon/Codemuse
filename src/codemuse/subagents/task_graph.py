"""Small dependency-aware scheduler for bounded subagent workflows."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskNode:
    node_id: str
    agent: str
    objective: str
    depends_on: list[str] = field(default_factory=list)
    allow_edits: bool = False
    status: str = "pending"
    error: str | None = None


class TaskGraph:
    def __init__(self, nodes: list[TaskNode]) -> None:
        self.nodes = {node.node_id: node for node in nodes}
        unknown = [dep for node in nodes for dep in node.depends_on if dep not in self.nodes]
        if unknown:
            raise ValueError(f"Unknown task dependency: {unknown[0]}")
        self._validate_acyclic()

    def batches(self) -> list[list[TaskNode]]:
        """Return deterministic runnable batches, including dependency ordering."""
        remaining = set(self.nodes)
        completed = {node_id for node_id, node in self.nodes.items() if node.status == "completed"}
        batches: list[list[TaskNode]] = []
        while remaining:
            ready = sorted(
                (self.nodes[node_id] for node_id in remaining),
                key=lambda node: node.node_id,
            )
            ready = [node for node in ready if all(dep in completed for dep in node.depends_on)]
            if not ready:
                raise ValueError("Task graph cannot make progress")
            batches.append(ready)
            for node in ready:
                remaining.remove(node.node_id)
                completed.add(node.node_id)
        return batches

    def mark(self, node_id: str, status: str, error: str | None = None) -> None:
        self.nodes[node_id].status = status
        self.nodes[node_id].error = error

    def _validate_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("Task graph contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in self.nodes[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self.nodes:
            visit(node_id)


__all__ = ["TaskGraph", "TaskNode"]
