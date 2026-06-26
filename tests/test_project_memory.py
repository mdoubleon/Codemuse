"""验证 project memory 相关功能在对外行为上符合预期。"""
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
from codemuse.app.bootstrap import DEFAULT_SYSTEM_PROMPT
from codemuse.domain.messages import ChatMessage
from codemuse.memory.file_memory_search import search_file_memory
from codemuse.memory.file_memory_store import FileMemoryStore
from codemuse.memory.retrieval_hook import MEMORY_RECALL_METADATA_KEY, MemoryContextProvider


class ProjectMemoryTests(unittest.TestCase):
    """ProjectMemoryTests：组织该功能的单元测试用例。"""
    def test_default_prompt_guides_project_memory_usage(self) -> None:
        self.assertIn("save_project_memory", DEFAULT_SYSTEM_PROMPT)
        self.assertIn("search_project_memory", DEFAULT_SYSTEM_PROMPT)

    def test_file_memory_store_and_search(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FileMemoryStore(root / ".data" / "codemuse" / "project_memory")
            saved = store.add(
                title="Runtime boundary",
                content="Runtime should orchestrate tools but not know external MCP protocol details.",
                category="architecture",
                tags=["runtime", "mcp"],
            )

            matches = search_file_memory(store, "runtime mcp", limit=3)

            self.assertEqual(matches[0].memory_id, saved.memory_id)

    def test_retrieval_hook_inserts_project_memory(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FileMemoryStore(root / ".data" / "codemuse" / "project_memory")
            store.add(
                title="Runtime tools rule",
                content="Runtime calls tools through ToolRegistry and keeps protocol details outside the loop.",
                category="architecture",
                tags=["runtime", "tools"],
            )
            provider = MemoryContextProvider(root)

            transformed = provider.transform_context(
                state=None,
                messages=[
                    ChatMessage.text("system", "You are CodeMuse."),
                    ChatMessage.text("user", "How should runtime call tools?"),
                ],
            )

            self.assertEqual(transformed[1].role, "system")
            self.assertIn(MEMORY_RECALL_METADATA_KEY, transformed[1].metadata)
            self.assertIn("Project Memory", transformed[1].text_content())
            self.assertIn("ToolRegistry", transformed[1].text_content())

    def test_runtime_stages_project_memory_save_for_approval(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            agent = build_agent(root)

            events = agent.prompt("remember this runtime should call tools through ToolRegistry")
            approvals = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0].tool_name, "save_project_memory")

            approved_events = agent.approve(str(approvals[0].details["approval_id"]))

            self.assertTrue(any(event.type == "checkpoint_created" for event in approved_events))
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "save_project_memory" for event in approved_events))

    def test_build_agent_upgrades_old_default_prompt_for_memory_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = build_agent(root)
            session_id = first.session_id

            record = first.session_store.load(session_id)
            record.system_prompt = "You are CodeMuse, a coding agent that can inspect a workspace with tools."
            first.session_store.save(record)

            restored = build_agent(root, session_id=session_id)

            self.assertIn("save_project_memory", restored.state.system_prompt)
            self.assertIn("search_project_memory", restored.state.system_prompt)


if __name__ == "__main__":
    unittest.main()
