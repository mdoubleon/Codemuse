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
from codemuse.domain.messages import ChatMessage
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


if __name__ == "__main__":
    unittest.main()
