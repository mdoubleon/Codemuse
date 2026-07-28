"""验证 subagents 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.bootstrap import build_agent
from codemuse.domain.tools import ToolCall
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.storage.sessions import SessionStore
from codemuse.subagents.manager import SubAgentManager
from codemuse.subagents.orchestrator import SubAgentOrchestrator
from codemuse.subagents.task_graph import TaskGraph, TaskNode
from codemuse.subagents.worktree import WorktreeHandle, WorktreeManager
from codemuse.tools.effects import build_tool_effect_preview


class SubAgentTests(unittest.TestCase):
    """SubAgentTests：组织该功能的单元测试用例。"""
    def test_manager_runs_read_only_subagent_with_allowlisted_tools(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            manager = SubAgentManager(
                workspace=root,
                parent_registry=agent.tool_registry,
                session_store=SessionStore(root / ".data" / "codemuse" / "sessions"),
            )

            result = manager.run_sync(spec_name="repo-researcher", task="list files", max_turns=2)

            self.assertEqual(result.status, "completed")
            self.assertIn("list_files", result.used_tools)
            self.assertNotIn("spawn_subagent", result.used_tools)
            self.assertIn("README.md", result.summary)

    def test_spawn_subagent_tool_runs_from_main_runtime(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)

            events = agent.prompt("use subagent to list files")
            tool_results = [event for event in events if event.type == "tool_result" and event.tool_name == "spawn_subagent"]

            self.assertEqual(len(tool_results), 1)
            payload = tool_results[0].details["subagent_result"]
            self.assertEqual(payload["spec_name"], "repo-researcher")
            self.assertIn("list_files", payload["used_tools"])

    def test_subagent_plan_runs_multiple_bounded_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)

            events = agent.prompt("run subagent plan")
            tool_results = [event for event in events if event.type == "tool_result" and event.tool_name == "run_subagent_plan"]

            self.assertEqual(len(tool_results), 1)
            payload = tool_results[0].details["subagent_plan"]
            self.assertEqual(payload["task_count"], 2)
            self.assertTrue(payload["parallel"])
            self.assertIn("list_files", payload["used_tools"])

    def test_task_graph_rejects_cycles_and_orders_dependencies(self) -> None:
        graph = TaskGraph([
            TaskNode("a", "repo-researcher", "research"),
            TaskNode("b", "repo-researcher", "review", ["a"]),
        ])
        self.assertEqual([[node.node_id for node in batch] for batch in graph.batches()], [["a"], ["b"]])
        with self.assertRaises(ValueError):
            TaskGraph([TaskNode("a", "repo-researcher", "a", ["b"]), TaskNode("b", "repo-researcher", "b", ["a"])])

    def test_orchestrate_agents_exposes_blackboard(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            result = agent.tool_registry.execute("orchestrate_agents", {"goal": "inspect repository", "workflow": "research"})
            payload = result.details["orchestration"]
            self.assertTrue(payload["success"])
            self.assertEqual(set(payload["blackboard"]), {"memory", "repo", "api"})

    def test_worktree_artifact_requires_parent_apply_tool(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
            manager = WorktreeManager(root)
            handle = manager.create(run_id="test-run", agent="code-worker")
            (Path(handle.worktree_path) / "README.md").write_text("# Changed in worktree\n", encoding="utf-8")
            artifact = manager.finalize(handle)
            self.assertIsNotNone(artifact)
            assert artifact is not None
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Sample\n\nA tiny project.\n")
            preview = build_tool_effect_preview(root, "apply_patch_artifact", {"artifact_id": artifact.artifact_id})
            self.assertFalse(preview["blocked"])
            agent = build_agent(root)
            tool = agent.tool_registry.get("apply_patch_artifact")
            self.assertTrue(tool.spec.requires_confirmation)
            tool.execute({"artifact_id": artifact.artifact_id})
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Changed in worktree\n")
            self.assertEqual("applied", manager.load_artifact(artifact.artifact_id).status)
            self.assertFalse(Path(handle.worktree_path).exists())

    def test_worktree_cleanup_refuses_unmanaged_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WorktreeManager(root)
            handle = WorktreeHandle("run", "agent", str(root), "head", "baseline", "digest")
            with self.assertRaises(PermissionError):
                manager.cleanup(handle)

    def test_code_change_orchestration_produces_reviewable_artifact_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
            agent = build_agent(root)
            manager = SubAgentManager(
                workspace=root,
                parent_registry=agent.tool_registry,
                session_store=SessionStore(root / ".data" / "codemuse" / "sessions"),
                llm_factory=_EditingProvider,
            )

            result = SubAgentOrchestrator(manager).run(goal="Update README", workflow="code_change", max_agents=6, allow_edits=True)

            self.assertTrue(result["success"], result)
            artifact = result["artifact"]
            self.assertIsNotNone(artifact)
            self.assertEqual("# Sample\n\nA tiny project.\n", (root / "README.md").read_text(encoding="utf-8"))
            runtime = build_agent(root)
            runtime.llm = _ArtifactApplyProvider(str(artifact["artifact_id"]))
            events = runtime.prompt("Apply the reviewed subagent artifact.")
            approval = next(event for event in events if event.type == "approval_required" and event.tool_name == "apply_patch_artifact")
            self.assertEqual("# Sample\n\nA tiny project.\n", (root / "README.md").read_text(encoding="utf-8"))
            runtime.approve(str(approval.details["approval_id"]))
            self.assertEqual("# Changed by code-worker\n", (root / "README.md").read_text(encoding="utf-8"))
            self.assertFalse(Path(str(artifact["worktree_path"])).exists())


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")


class _EditingProvider:
    def __init__(self) -> None:
        self._used_tool = False

    @property
    def info(self) -> LLMProviderInfo:
        return LLMProviderInfo(provider="test", model="editing-test")

    def complete(self, messages, tools) -> LLMResponse:
        available = {tool.name for tool in tools}
        if "write_file" in available and not self._used_tool:
            self._used_tool = True
            return LLMResponse(tool_calls=[ToolCall(id="write-1", name="write_file", arguments={"path": "README.md", "content": "# Changed by code-worker\n", "overwrite": True})])
        return LLMResponse(text="completed")


class _ArtifactApplyProvider:
    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        self._used_tool = False

    @property
    def info(self) -> LLMProviderInfo:
        return LLMProviderInfo(provider="test", model="artifact-test")

    def complete(self, messages, tools) -> LLMResponse:
        if not self._used_tool:
            self._used_tool = True
            return LLMResponse(tool_calls=[ToolCall(id="artifact-1", name="apply_patch_artifact", arguments={"artifact_id": self.artifact_id})])
        return LLMResponse(text="applied")


if __name__ == "__main__":
    unittest.main()
