from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codemuse.domain.messages import ChatMessage
from codemuse.learning.extractor import LearningExtractor
from codemuse.learning.runtime import LearningRuntime
from codemuse.learning.safety import learning_text_rejection_reason
from codemuse.storage.sessions import SessionStore


class LearningTests(unittest.TestCase):
    def test_extracts_explicit_durable_instruction(self) -> None:
        items = LearningExtractor().extract("Remember: always run unit tests before release.", session_id="s1", turn_id="2")
        self.assertEqual(1, len(items))
        self.assertEqual("project_convention", items[0].kind)
        self.assertEqual("high", items[0].confidence)

    def test_rejects_secrets_and_transient_logs(self) -> None:
        self.assertEqual("possible_secret", learning_text_rejection_reason("remember api_key=abcdefghijklmnop"))
        self.assertEqual("transient_log", learning_text_rejection_reason("remember this\nTraceback (most recent call last):\nerror"))
        self.assertEqual([], LearningExtractor().extract("记住 password=abcdefghijklmnop", session_id="s1", turn_id="1"))

    def test_persisted_turn_is_deduplicated_and_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            sessions = SessionStore(workspace / ".data" / "codemuse" / "sessions")
            record = sessions.create("system")
            record.messages.append(ChatMessage.text("user", "记住：这个项目总是先运行单元测试。"))
            sessions.save(record)
            runtime = LearningRuntime(workspace, session_store=sessions)

            first = runtime.on_turn_persisted(record.session_id, "1")
            second = runtime.on_turn_persisted(record.session_id, "1")

            self.assertEqual(1, len(first))
            self.assertEqual([], second)
            self.assertEqual("pending", runtime.store.get(first[0].candidate_id).status)
            applied = runtime.approve(first[0].candidate_id)
            self.assertEqual("applied", applied.status)
            self.assertTrue(applied.memory_id)
            self.assertEqual(1, len(list((workspace / ".data" / "codemuse" / "project_memory" / "items").glob("*.json"))))

    def test_reject_does_not_write_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            runtime = LearningRuntime(workspace)
            candidate = LearningExtractor().extract("Never commit generated logs.", session_id="s", turn_id="1")[0]
            runtime.store.append([candidate])
            rejected = runtime.reject(candidate.candidate_id)
            self.assertEqual("rejected", rejected.status)
            self.assertFalse((workspace / ".data" / "codemuse" / "project_memory").exists())


if __name__ == "__main__":
    unittest.main()
