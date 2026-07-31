"""Verify persisted session branching and tree construction."""
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

from codemuse.api import sdk
from codemuse.app.bootstrap import build_agent
from codemuse.domain.messages import ChatMessage
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.storage.sessions import SessionStore


class SessionTreeTests(unittest.TestCase):
    def test_legacy_record_loads_as_tree_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = SessionStore(Path(raw))
            session_id = "legacy-session"
            (Path(raw) / f"{session_id}.json").write_text(
                json.dumps({"session_id": session_id, "system_prompt": "legacy", "messages": []}),
                encoding="utf-8",
            )

            record = store.load(session_id)

            self.assertIsNone(record.parent_session_id)
            self.assertEqual(record.root_session_id, session_id)
            self.assertEqual(record.depth, 0)

    def test_fork_copies_context_and_then_evolves_independently(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = SessionStore(Path(raw))
            parent = store.create("system")
            parent.messages.append(ChatMessage.text("user", "shared context"))
            store.save(parent)

            child = store.fork(parent.session_id)
            child.messages.append(ChatMessage.text("user", "child only"))
            store.save(child)

            restored_parent = store.load(parent.session_id)
            restored_child = store.load(child.session_id)
            self.assertEqual(restored_child.parent_session_id, parent.session_id)
            self.assertEqual(restored_child.root_session_id, parent.session_id)
            self.assertEqual(restored_child.depth, 1)
            self.assertEqual(restored_child.forked_at_message, 1)
            self.assertEqual(len(restored_parent.messages), 1)
            self.assertEqual(len(restored_child.messages), 2)

    def test_sdk_lists_nested_session_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            store = SessionStore(workspace / ".data" / "codemuse" / "sessions")
            root = store.create("system")
            store.save(root)
            child = store.fork(root.session_id)
            store.save(child)
            grandchild = store.fork(child.session_id)
            store.save(grandchild)

            tree = sdk.list_session_tree(workspace)

            self.assertEqual([item["session_id"] for item in tree], [root.session_id])
            self.assertEqual(tree[0]["children"][0]["session_id"], child.session_id)
            self.assertEqual(tree[0]["children"][0]["children"][0]["session_id"], grandchild.session_id)

    def test_turn_head_navigation_preserves_sibling_branches(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = SessionStore(Path(raw))
            record = store.create("system")
            first_head = "first-head"
            second_head = "second-head"
            alternate_head = "alternate-head"

            record.messages = [ChatMessage.text("user", "first")]
            record.turns = [{"turn_node_id": first_head, "parent_head_id": None, "message_count": 1}]
            record.active_head_id = first_head
            store.save(record)

            record.messages.append(ChatMessage.text("assistant", "second branch"))
            record.turns.append({"turn_node_id": second_head, "parent_head_id": first_head, "message_count": 2})
            record.active_head_id = second_head
            store.save(record)

            restored_first = store.set_active_head(record.session_id, first_head)
            self.assertEqual([item.text_content() for item in restored_first.messages], ["first"])
            restored_first.messages.append(ChatMessage.text("assistant", "alternate branch"))
            restored_first.turns.append({"turn_node_id": alternate_head, "parent_head_id": first_head, "message_count": 2})
            restored_first.active_head_id = alternate_head
            store.save(restored_first)

            restored_second = store.set_active_head(record.session_id, second_head)
            self.assertEqual([item.text_content() for item in restored_second.messages], ["first", "second branch"])
            restored_alternate = store.set_active_head(record.session_id, alternate_head)
            self.assertEqual([item.text_content() for item in restored_alternate.messages], ["first", "alternate branch"])

    def test_sdk_exposes_resume_branch_and_head_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            store = SessionStore(workspace / ".data" / "codemuse" / "sessions")
            record = store.create("system")
            record.messages = [ChatMessage.text("user", "root context")]
            record.turns = [{"turn_node_id": "root-head", "parent_head_id": None, "message_count": 1}]
            record.active_head_id = "root-head"
            store.save(record)

            resumed = sdk.resume_session(workspace, record.session_id)
            branch = sdk.branch_session(workspace, record.session_id, head_id="root-head")
            navigated = sdk.navigate_session_head(workspace, record.session_id, "root-head")

            self.assertEqual(resumed["session_id"], record.session_id)
            self.assertEqual(branch["parent_session_id"], record.session_id)
            self.assertEqual(branch["active_head_id"], "root-head")
            self.assertEqual(navigated["message_count"], 1)

    def test_pending_approval_isolated_to_the_staging_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.prompt("hello")
            base_head_id = agent.session.active_head_id
            staged = agent.prompt("write file notes/branch-only.txt content: branch only")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            staging_head_id = agent.session.active_head_id
            target = workspace / "notes" / "branch-only.txt"
            approvals = PendingApprovalStore(workspace / ".data" / "codemuse" / "approvals")

            self.assertNotEqual(base_head_id, staging_head_id)
            self.assertEqual(approvals.load(approval_id).details["head_id"], staging_head_id)

            sessions = SessionStore(workspace / ".data" / "codemuse" / "sessions")
            sessions.set_active_head(agent.session_id, str(base_head_id))
            sibling = build_agent(workspace, session_id=agent.session_id)
            sibling.memory_provider = None

            self.assertEqual(sibling.state.pending_tool_calls, [])
            with self.assertRaisesRegex(ValueError, "different session head"):
                sibling.approve(approval_id)
            self.assertEqual(approvals.load(approval_id).status, "pending")
            self.assertFalse(target.exists())

            sessions.set_active_head(agent.session_id, str(staging_head_id))
            restored = build_agent(workspace, session_id=agent.session_id)
            restored.memory_provider = None
            self.assertEqual([call.id for call in restored.state.pending_tool_calls], [approvals.load(approval_id).tool_call_id])
            restored.approve(approval_id)
            self.assertEqual(target.read_text(encoding="utf-8"), "branch only\n")

    def test_legacy_pending_approval_uses_active_message_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.prompt("hello")
            base_head_id = agent.session.active_head_id
            staged = agent.prompt("write file notes/legacy.txt content: legacy")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            staging_head_id = agent.session.active_head_id
            approvals = PendingApprovalStore(workspace / ".data" / "codemuse" / "approvals")
            legacy = approvals.load(approval_id)
            legacy.details.pop("head_id", None)
            approvals.save(legacy)

            sessions = SessionStore(workspace / ".data" / "codemuse" / "sessions")
            sessions.set_active_head(agent.session_id, str(base_head_id))
            sibling = build_agent(workspace, session_id=agent.session_id)
            self.assertEqual(sibling.state.pending_tool_calls, [])

            sessions.set_active_head(agent.session_id, str(staging_head_id))
            restored = build_agent(workspace, session_id=agent.session_id)
            self.assertEqual([call.id for call in restored.state.pending_tool_calls], [legacy.tool_call_id])

    def test_sibling_unresolved_execution_blocks_new_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.prompt("hello")
            base_head_id = agent.session.active_head_id
            staged = agent.prompt("write file notes/in-flight.txt content: pending")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))
            agent.approval_store.begin_execution(approval_id, execution_id="other-head-execution")

            sessions = SessionStore(workspace / ".data" / "codemuse" / "sessions")
            sessions.set_active_head(agent.session_id, str(base_head_id))
            sibling = build_agent(workspace, session_id=agent.session_id)

            self.assertEqual(sibling.state.phase, "execution_recovery_required")
            self.assertEqual(sibling.state.pending_tool_calls, [])
            with self.assertRaisesRegex(RuntimeError, "unresolved approvals"):
                sibling.prompt("continue on this branch")


if __name__ == "__main__":
    unittest.main()
