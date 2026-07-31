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
from codemuse.domain.messages import ChatMessage
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.runtime.compaction import ConversationCompactor


class _TextLLM:
    @property
    def info(self) -> LLMProviderInfo:
        return LLMProviderInfo(provider="test", model="context-layers")

    def complete(self, _messages, _tools) -> LLMResponse:
        return LLMResponse(text="done")


class ContextLayerTests(unittest.TestCase):
    def test_long_history_is_compacted_before_the_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            agent.llm = _TextLLM()
            agent.compactor = ConversationCompactor(threshold_tokens=1, keep_messages=2, summary_chars=500)
            agent.state.messages = [
                ChatMessage.text("user", "old requirement alpha"),
                ChatMessage.text("assistant", "old answer alpha"),
                ChatMessage.text("user", "old requirement beta"),
                ChatMessage.text("assistant", "old answer beta"),
            ]

            agent.prompt("current task")

            summaries = [message for message in agent.state.messages if message.metadata.get("compacted")]
            self.assertEqual(len(summaries), 1)
            self.assertIn("old requirement alpha", summaries[0].text_content())
            self.assertEqual(agent.state.messages[-2].text_content(), "current task")
            self.assertEqual(agent.state.messages[-1].text_content(), "done")


if __name__ == "__main__":
    unittest.main()
