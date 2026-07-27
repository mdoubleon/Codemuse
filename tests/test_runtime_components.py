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
from codemuse.runtime.compaction import ConversationCompactor
from codemuse.runtime.hooks import RuntimeHooks
from codemuse.runtime.session_host import SessionHost
from codemuse.domain.messages import ChatMessage


class RuntimeComponentTests(unittest.TestCase):
    def test_context_hook_and_tool_hook_are_wired(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# demo", encoding="utf-8")
            hooks = RuntimeHooks(transform_context=[lambda _state, messages: [*messages, ChatMessage.text("system", "hook")]])
            agent = build_agent(root)
            agent.hooks = hooks
            agent.emitter = agent.emitter.__class__()
            hooks.register_with_lifecycle(agent.emitter)
            messages = agent._messages_for_model()
            self.assertEqual(messages[-1].text_content(), "hook")

    def test_compactor_preserves_recent_messages(self) -> None:
        messages = [ChatMessage.text("user", f"old {i}") for i in range(20)] + [ChatMessage.text("user", "latest")]
        result = ConversationCompactor(threshold_tokens=20, keep_messages=4).compact(messages, lambda values: sum(len(m.text_content()) for m in values))
        self.assertTrue(result.compacted)
        self.assertEqual(result.messages[-1].text_content(), "latest")
        self.assertTrue(result.messages[0].metadata.get("compacted"))

    def test_enqueue_message_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            agent = build_agent(root)
            agent.enqueue_message("steer me", delivery="steering")
            restored = build_agent(root, session_id=agent.session_id)
            self.assertEqual(restored.state.queued_messages[0].text, "steer me")

    def test_session_host_can_create_and_fork(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            host = SessionHost()
            runtime = host.create_session(root)
            fork = host.fork_session(root, runtime.session_id)
            self.assertEqual(fork.source_session_id, runtime.session_id)
            self.assertTrue(any(item["session_id"] == fork.session_id for item in host.list_sessions(root)))

    def test_runtime_emits_stream_deltas_and_persists_turn_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# demo", encoding="utf-8")
            agent = build_agent(root)
            events = agent.prompt("list files")
            self.assertTrue(any(event.type == "message_delta" for event in events))
            self.assertIsNotNone(agent.session.active_head_id)
            restored = build_agent(root, session_id=agent.session_id)
            self.assertEqual(restored.session.active_head_id, agent.session.active_head_id)
            self.assertTrue(restored.session.turns)


if __name__ == "__main__":
    unittest.main()
