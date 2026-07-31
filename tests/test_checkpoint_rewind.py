"""验证 checkpoint rewind 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import json
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
from codemuse.storage.sessions import SessionStore
from codemuse.api import sdk


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
            checkpoint = CheckpointStore(root / ".data" / "codemuse" / "checkpoints").load(checkpoint_id)
            snapshot = [message.to_dict() for message in agent.state.messages]

            agent.prompt("list files")
            self.assertGreater(len(agent.state.messages), len(snapshot))

            rewind_events = agent.rewind(checkpoint_id)

            self.assertTrue(any(event.type == "checkpoint_rewound" for event in rewind_events))
            self.assertEqual(snapshot, [message.to_dict() for message in agent.state.messages])
            self.assertEqual(checkpoint.metadata["head_id"], agent.session.active_head_id)

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

    def test_preview_and_conversation_only_rewind_do_not_change_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            agent.prompt("hello")
            checkpoint_id = str(agent.create_checkpoint("before changes")[0].details["checkpoint_id"])
            target = root / "README.md"
            target.write_text("changed outside rewind\n", encoding="utf-8")
            preview = agent.preview_rewind(checkpoint_id, mode="conversation_only")
            self.assertEqual(preview["restore_preview"], {})
            agent.prompt("list files")
            agent.rewind(checkpoint_id, mode="conversation_only")
            self.assertEqual(target.read_text(encoding="utf-8"), "changed outside rewind\n")

    def test_workspace_only_rewind_preserves_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            checkpoint_id = str(agent.create_checkpoint("workspace")[0].details["checkpoint_id"])
            target = root / "README.md"
            original = target.read_text(encoding="utf-8")
            target.write_text("changed\n", encoding="utf-8")
            agent.prompt("hello")
            messages = [item.to_dict() for item in agent.state.messages]
            agent.rewind(checkpoint_id, mode="workspace_only")
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual([item.to_dict() for item in agent.state.messages], messages)
            self.assertEqual(sdk.preview_rewind(root, checkpoint_id, session_id=agent.session_id)["checkpoint_id"], checkpoint_id)

    def test_conversation_rewind_invalidates_later_pending_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"
            original = target.read_text(encoding="utf-8")
            agent = build_agent(root)
            checkpoint_id = str(agent.create_checkpoint("before approval")[0].details["checkpoint_id"])

            staged = agent.prompt("write file README.md content: # Later change")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))

            rewound = agent.rewind(checkpoint_id)
            approval = agent.approval_store.load(approval_id)

            self.assertEqual("stale", approval.status)
            self.assertIn(approval_id, next(event for event in rewound if event.type == "checkpoint_rewound").details["invalidated_approval_ids"])
            retried = agent.approve(approval_id)
            self.assertTrue(any(event.type == "approval_stale" for event in retried))
            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_conversation_rewind_invalidates_completed_later_approval_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"
            original = target.read_text(encoding="utf-8")
            agent = build_agent(root)
            checkpoint_id = str(agent.create_checkpoint("before approved change")[0].details["checkpoint_id"])

            staged = agent.prompt("write file README.md content: # Changed after checkpoint")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            agent.approve(approval_id)
            self.assertEqual("# Changed after checkpoint\n", target.read_text(encoding="utf-8"))

            agent.rewind(checkpoint_id)
            self.assertEqual("stale", agent.approval_store.load(approval_id).status)
            replay = agent.approve(approval_id)

            self.assertTrue(any(event.type == "approval_stale" for event in replay))
            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_rewind_restores_pending_approval_that_existed_at_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"
            agent = build_agent(root)
            staged = agent.prompt("write file README.md content: # Checkpoint pending")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            checkpoint_id = str(agent.create_checkpoint("pending approval")[0].details["checkpoint_id"])

            agent.rewind(checkpoint_id)

            self.assertEqual("pending", agent.approval_store.load(approval_id).status)
            self.assertEqual("awaiting_approval", agent.state.phase)
            agent.approve(approval_id)
            self.assertEqual("# Checkpoint pending\n", target.read_text(encoding="utf-8"))

    def test_rewind_refuses_later_unresolved_approval_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            checkpoint_id = str(agent.create_checkpoint("before ambiguous execution")[0].details["checkpoint_id"])
            staged = agent.prompt("write file README.md content: # Never execute")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            agent.approval_store.begin_execution(approval_id, execution_id="ambiguous-execution")

            with self.assertRaisesRegex(RuntimeError, "approval execution is unresolved"):
                agent.rewind(checkpoint_id)

            self.assertEqual("executing", agent.approval_store.load(approval_id).execution_status)

    def test_rewind_refuses_execution_that_already_existed_at_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            staged = agent.prompt("write file README.md content: # Ambiguous")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            agent.approval_store.begin_execution(approval_id, execution_id="already-executing")
            checkpoint_id = str(agent.create_checkpoint("during ambiguous execution")[0].details["checkpoint_id"])

            with self.assertRaisesRegex(RuntimeError, "approval execution is unresolved"):
                agent.rewind(checkpoint_id)

            self.assertEqual("executing", agent.approval_store.load(approval_id).execution_status)

    def test_rewind_refuses_unresolved_execution_on_a_sibling_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            agent.prompt("hello")
            base_head_id = agent.session.active_head_id
            checkpoint_id = str(agent.create_checkpoint("before sibling execution")[0].details["checkpoint_id"])
            agent.prompt("hello from sibling")
            sibling_head_id = agent.session.active_head_id

            sessions = SessionStore(root / ".data" / "codemuse" / "sessions")
            sessions.set_active_head(agent.session_id, str(base_head_id))
            staging = build_agent(root, session_id=agent.session_id)
            staged = staging.prompt("write file README.md content: # Other branch")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            staging.approval_store.begin_execution(approval_id, execution_id="sibling-executing")

            sessions.set_active_head(agent.session_id, str(sibling_head_id))
            sibling = build_agent(root, session_id=agent.session_id)

            with self.assertRaisesRegex(RuntimeError, "approval execution is unresolved"):
                sibling.rewind(checkpoint_id)

            self.assertEqual("executing", staging.approval_store.load(approval_id).execution_status)

    def test_corrupt_snapshot_is_rejected_before_workspace_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            checkpoint_id = str(agent.create_checkpoint("integrity")[0].details["checkpoint_id"])
            checkpoint = CheckpointStore(root / ".data" / "codemuse" / "checkpoints").load(checkpoint_id)
            snapshot_path = Path(str(checkpoint.metadata["workspace_snapshot"]["snapshot_path"]))
            manifest = json.loads((snapshot_path / "manifest.json").read_text(encoding="utf-8"))
            first_file = snapshot_path / "files" / str(manifest["files"][0]["relative_path"])
            first_file.write_text("corrupt snapshot\n", encoding="utf-8")

            target = root / "README.md"
            target.write_text("current workspace must survive\n", encoding="utf-8")
            extra = root / "current-only.txt"
            extra.write_text("keep me\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "integrity validation"):
                agent.rewind(checkpoint_id)

            self.assertEqual("current workspace must survive\n", target.read_text(encoding="utf-8"))
            self.assertEqual("keep me\n", extra.read_text(encoding="utf-8"))

    def test_snapshot_checkpoint_identity_must_match_before_rewind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            checkpoint_id = str(agent.create_checkpoint("identity")[0].details["checkpoint_id"])
            checkpoint = CheckpointStore(root / ".data" / "codemuse" / "checkpoints").load(checkpoint_id)
            snapshot_path = Path(str(checkpoint.metadata["workspace_snapshot"]["snapshot_path"]))
            manifest_path = snapshot_path / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["checkpoint_id"] = "different-checkpoint"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            target = root / "README.md"
            target.write_text("do not touch\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not match checkpoint"):
                agent.rewind(checkpoint_id)

            self.assertEqual("do not touch\n", target.read_text(encoding="utf-8"))


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
