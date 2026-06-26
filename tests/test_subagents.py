"""验证 subagents 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.bootstrap import build_agent
from codemuse.storage.sessions import SessionStore
from codemuse.subagents.manager import SubAgentManager


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
            self.assertIn("list_files", payload["used_tools"])


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
