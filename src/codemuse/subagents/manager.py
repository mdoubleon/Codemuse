"""创建受限子 Agent Runtime，用 allowlist 工具执行子任务。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path

from codemuse.llm.fake import FakeLLM
from codemuse.llm.provider.base import LLMProvider
from codemuse.memory.retrieval_hook import MemoryContextProvider
from codemuse.runtime.runtime import AgentRuntime
from codemuse.runtime.cancellation import CancellationToken
from codemuse.storage.sessions import SessionStore
from codemuse.subagents.catalog import SubAgentCatalog
from codemuse.subagents.specs import SubAgentRunResult
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.policy import ALLOW, ToolPolicyDecision, ToolPolicyEvaluator


class _WorktreePolicyEvaluator(ToolPolicyEvaluator):
    """Allow file mutations only inside an already isolated worktree runtime."""

    def evaluate(self, spec):
        if spec.permission_domain == "write" and spec.name in {"write_file", "replace_text", "apply_patch"}:
            return ToolPolicyDecision(action=ALLOW, reason="isolated worktree mutation")
        return super().evaluate(spec)


class SubAgentManager:
    """运行受限子 Agent。

    子 Agent 复用 AgentRuntime，只能看到 allowlist 中的工具；管理器同时支持
    单任务和有并发上限的批量研究任务，写操作必须在隔离 worktree 中执行。
    """

    def __init__(
        self,
        *,
        workspace: Path,
        parent_registry: ToolRegistry,
        session_store: SessionStore,
        catalog: SubAgentCatalog | None = None,
        llm_factory: Callable[[], LLMProvider] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self.workspace = workspace.resolve()
        self.parent_registry = parent_registry
        self.session_store = session_store
        self.catalog = catalog or SubAgentCatalog()
        self.llm_factory = llm_factory or (lambda: FakeLLM())
        self.cancellation_token = cancellation_token or CancellationToken()

    def list_specs(self) -> list[str]:
        """列出当前已注册的子 Agent 规格。"""
        return self.catalog.names()

    def run_sync(self, *, spec_name: str, task: str, max_turns: int | None = None, tool_workspace: Path | None = None) -> SubAgentRunResult:
        """同步创建受限子 Runtime，执行子任务并整理子 Agent 结果。"""
        started_at = time.time()
        spec = self.catalog.get(spec_name)
        workspace = (tool_workspace or self.workspace).resolve()
        child_registry = self._restricted_registry(spec.tool_allowlist, workspace=workspace)
        child_session = self.session_store.create(spec.system_prompt)
        self.session_store.save(child_session)
        runtime = AgentRuntime(
            workspace=workspace,
            llm=self.llm_factory(),
            tool_registry=child_registry,
            session_store=self.session_store,
            session=child_session,
            memory_provider=MemoryContextProvider(self.workspace),
            max_turns=max_turns or spec.max_turns,
            cancellation_token=self.cancellation_token,
            policy_evaluator=_WorktreePolicyEvaluator() if tool_workspace else None,
        )
        events = runtime.prompt(task)
        used_tools = [event.tool_name for event in events if event.tool_name and event.type in {"tool_call", "tool_result"}]
        final_messages = [event.message for event in events if event.type == "message" and event.message]
        summary = final_messages[-1] if final_messages else "Subagent finished without a final message."
        findings = [summary]
        return SubAgentRunResult.create(
            spec_name=spec.name,
            task=task,
            summary=summary,
            findings=findings,
            used_tools=sorted(set(used_tools)),
            events=[event.to_dict() for event in events],
            started_at=started_at,
        )

    def run_plan(self, *, tasks: list[str], spec_name: str = "repo-researcher", max_turns: int | None = None, parallel: bool = True, max_workers: int = 4) -> dict[str, object]:
        """Run bounded subagent tasks, optionally in parallel, and aggregate traces."""
        clean_tasks = [task.strip() for task in tasks if task.strip()]
        if not clean_tasks:
            raise ValueError("subagent plan requires at least one task")
        if parallel and len(clean_tasks) > 1:
            workers = max(1, min(int(max_workers), 4, len(clean_tasks)))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="codemuse-subagent") as executor:
                futures = [executor.submit(self.run_sync, spec_name=spec_name, task=task, max_turns=max_turns) for task in clean_tasks]
                results = [future.result() for future in futures]
        else:
            results = [self.run_sync(spec_name=spec_name, task=task, max_turns=max_turns) for task in clean_tasks]
        return {
            "status": "completed",
            "spec_name": spec_name,
            "task_count": len(results),
            "parallel": bool(parallel and len(clean_tasks) > 1),
            "max_workers": min(int(max_workers), 4),
            "summaries": [result.summary for result in results],
            "used_tools": sorted({tool for result in results for tool in result.used_tools}),
            "results": [result.to_dict() for result in results],
        }

    def _restricted_registry(self, allowlist: list[str], *, workspace: Path | None = None) -> ToolRegistry:
        """为子 Agent 构造只包含 allowlist 工具的受限注册表。"""
        workspace = (workspace or self.workspace).resolve()
        child = ToolRegistry(workspace)
        for name in allowlist:
            if name == "spawn_subagent":
                continue
            if name not in self.parent_registry.metadata():
                continue
            tool = self.parent_registry.get(name)
            if not tool.spec.model_callable:
                continue
            # 只读任务可复用实例；worktree 写任务必须用隔离 workspace 重建工具。
            if workspace != self.workspace:
                try:
                    tool = type(tool)(workspace)
                except TypeError as exc:
                    raise RuntimeError(f"Tool {name} cannot be isolated in a worktree") from exc
            child.register(tool, category=self.parent_registry.metadata()[name].category)
        return child
