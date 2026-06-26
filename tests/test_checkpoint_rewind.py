"""验证 checkpoint rewind 相关功能在对外行为上符合预期。"""
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
from codemuse.storage.checkpoints import CheckpointStore


class CheckpointRewindTests(unittest.TestCase):
    """CheckpointRewindTests：组织该功能的单元测试用例。"""
    def test_manual_checkpoint_can_restore_session_messages(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)

            agent.prompt("hello")
            checkpoint_events = agent.create_checkpoint("after greeting")
            checkpoint_id = str(checkpoint_events[0].details["checkpoint_id"])
            snapshot = [message.to_dict() for message in agent.state.messages]

            agent.prompt("list files")
            self.assertGreater(len(agent.state.messages), len(snapshot))

            rewind_events = agent.rewind(checkpoint_id)

            self.assertTrue(any(event.type == "checkpoint_rewound" for event in rewind_events))
            self.assertEqual(snapshot, [message.to_dict() for message in agent.state.messages])

    def test_side_effect_tool_creates_checkpoint_before_execution(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)

            events = agent.prompt("learn repo and save memory")
            approval_events = [event for event in events if event.type == "approval_required"]
            self.assertEqual(len(approval_events), 1)
            approval_id = str(approval_events[0].details["approval_id"])

            approved_events = agent.approve(approval_id)
            checkpoint_events = [event for event in approved_events if event.type == "checkpoint_created"]
            store = CheckpointStore(root / ".data" / "codemuse" / "checkpoints")
            checkpoints = store.list(session_id=agent.session_id)

            self.assertEqual(len(checkpoint_events), 1)
            self.assertTrue(any(item.metadata.get("tool_name") == "save_blueprint_memory" for item in checkpoints))
            self.assertTrue(any(item.metadata.get("workspace_snapshot") for item in checkpoints))

    def test_rewind_restores_workspace_file_content(self) -> None:
        """验证工具执行前的 checkpoint 能把被修改文件恢复到执行前。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"
            original = target.read_text(encoding="utf-8")
            agent = build_agent(root)

            events = agent.prompt("write file README.md content: # Changed by tool")
            approval_id = str([event for event in events if event.type == "approval_required"][0].details["approval_id"])
            approved_events = agent.approve(approval_id)
            checkpoint_id = str([event for event in approved_events if event.type == "checkpoint_created"][0].details["checkpoint_id"])

            self.assertEqual(target.read_text(encoding="utf-8"), "# Changed by tool\n")

            rewind_events = agent.rewind(checkpoint_id)

            self.assertEqual(target.read_text(encoding="utf-8"), original)
            rewind_event = [event for event in rewind_events if event.type == "checkpoint_rewound"][0]
            self.assertTrue(rewind_event.details["restored_workspace"])
            self.assertGreaterEqual(rewind_event.details["workspace_restore"]["restored_files_count"], 1)

    def test_rewind_removes_files_created_after_checkpoint(self) -> None:
        """验证 checkpoint 后新增的 workspace 文件会在 rewind 时被删除。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "notes" / "created.txt"
            agent = build_agent(root)

            events = agent.prompt("write file notes/created.txt content: new file")
            approval_id = str([event for event in events if event.type == "approval_required"][0].details["approval_id"])
            approved_events = agent.approve(approval_id)
            checkpoint_id = str([event for event in approved_events if event.type == "checkpoint_created"][0].details["checkpoint_id"])

            self.assertTrue(target.exists())

            agent.rewind(checkpoint_id)

            self.assertFalse(target.exists())


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text(
        "# Sample Agent\n\nA tiny coding agent that can save blueprint memory.\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text('[project]\nname = "sample-agent"\n', encoding="utf-8")
    for folder in ["src/sample/runtime", "src/sample/tools", "src/sample/storage"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "src/sample/runtime/runtime.py").write_text("class AgentRuntime:\n    pass\n", encoding="utf-8")
    (root / "src/sample/tools/registry.py").write_text("class ToolRegistry:\n    pass\n", encoding="utf-8")
    (root / "src/sample/storage/sessions.py").write_text("class SessionStore:\n    pass\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
