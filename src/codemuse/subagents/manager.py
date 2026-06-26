"""创建受限子 Agent Runtime，用 allowlist 工具执行子任务。"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from codemuse.llm.fake import FakeLLM
from codemuse.llm.provider.base import LLMProvider
from codemuse.memory.retrieval_hook import MemoryContextProvider
from codemuse.runtime.runtime import AgentRuntime
from codemuse.storage.sessions import SessionStore
from codemuse.subagents.catalog import SubAgentCatalog
from codemuse.subagents.specs import SubAgentRunResult
from codemuse.tools.registry import ToolRegistry


class SubAgentManager:
    """运行受限子 Agent。

    Stage 10 先实现单个同步子任务。子 Agent 复用 AgentRuntime，
    但只能看到 allowlist 中的工具，避免递归和越权。
    """

    def __init__(
        self,
        *,
        workspace: Path,
        parent_registry: ToolRegistry,
        session_store: SessionStore,
        catalog: SubAgentCatalog | None = None,
        llm_factory: Callable[[], LLMProvider] | None = None,
    ) -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self.workspace = workspace.resolve()
        self.parent_registry = parent_registry
        self.session_store = session_store
        self.catalog = catalog or SubAgentCatalog()
        self.llm_factory = llm_factory or (lambda: FakeLLM())

    def list_specs(self) -> list[str]:
        """列出该领域的已保存或已加载数据。"""
        return self.catalog.names()

    def run_sync(self, *, spec_name: str, task: str, max_turns: int | None = None) -> SubAgentRunResult:
        """同步创建受限子 Runtime，执行子任务并整理子 Agent 结果。"""
        started_at = time.time()
        spec = self.catalog.get(spec_name)
        child_registry = self._restricted_registry(spec.tool_allowlist)
        child_session = self.session_store.create(spec.system_prompt)
        self.session_store.save(child_session)
        runtime = AgentRuntime(
            workspace=self.workspace,
            llm=self.llm_factory(),
            tool_registry=child_registry,
            session_store=self.session_store,
            session=child_session,
            memory_provider=MemoryContextProvider(self.workspace),
            max_turns=max_turns or spec.max_turns,
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

    def run_plan(self, *, tasks: list[str], spec_name: str = "repo-researcher", max_turns: int | None = None) -> dict[str, object]:
        """Run a bounded sequence of subagent tasks and return an aggregate trace."""
        clean_tasks = [task.strip() for task in tasks if task.strip()]
        if not clean_tasks:
            raise ValueError("subagent plan requires at least one task")
        results = [self.run_sync(spec_name=spec_name, task=task, max_turns=max_turns) for task in clean_tasks]
        return {
            "status": "completed",
            "spec_name": spec_name,
            "task_count": len(results),
            "summaries": [result.summary for result in results],
            "used_tools": sorted({tool for result in results for tool in result.used_tools}),
            "results": [result.to_dict() for result in results],
        }

    def _restricted_registry(self, allowlist: list[str]) -> ToolRegistry:
        """为该流程的公共逻辑提供局部辅助处理。"""
        child = ToolRegistry(self.workspace)
        for name in allowlist:
            if name == "spawn_subagent":
                continue
            if name not in self.parent_registry.metadata():
                continue
            tool = self.parent_registry.get(name)
            if not tool.spec.model_callable:
                continue
            # 当前阶段复用只读工具实例；后续 worktree 子 Agent 再做隔离工具实例。
            child.register(tool, category=self.parent_registry.metadata()[name].category)
        return child
