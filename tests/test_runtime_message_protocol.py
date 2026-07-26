"""验证 Runtime 发给模型的消息满足工具调用协议。"""
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
from codemuse.domain.messages import ChatMessage, TextPart
from codemuse.domain.tools import ToolCall


class RuntimeMessageProtocolTests(unittest.TestCase):
    """覆盖 OpenAI-compatible provider 对 tool 消息顺序的要求。"""

    def test_context_window_keeps_tool_call_before_tool_result(self) -> None:
        """最近消息窗口从 tool 开始时，也要把对应 assistant tool_calls 一起带上。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            call = ToolCall(id="call_1", name="list_files", arguments={"path": "."})
            tool_result = ChatMessage(
                role="tool",
                tool_call_id="call_1",
                tool_name="list_files",
                content=[TextPart(text="README.md")],
            )
            agent.state.messages = [
                ChatMessage(role="assistant", tool_calls=[call]),
                tool_result,
                *[ChatMessage.text("assistant", f"filler {index}") for index in range(18)],
                ChatMessage.text("user", "next task"),
            ]

            messages = agent._messages_for_model()

            first_tool_index = next(index for index, message in enumerate(messages) if message.role == "tool")
            previous = messages[first_tool_index - 1]
            self.assertEqual(previous.role, "assistant")
            self.assertEqual(previous.tool_calls[0].id, "call_1")

    def test_orphan_tool_result_is_downgraded_to_assistant_observation(self) -> None:
        """无法配对的 tool 结果不能原样发给 OpenAI-compatible provider。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            agent.state.messages = [
                ChatMessage(
                    role="tool",
                    tool_call_id="missing_call",
                    tool_name="read_file",
                    content=[TextPart(text="orphan result")],
                ),
                ChatMessage.text("user", "continue"),
            ]

            messages = agent._messages_for_model()

            self.assertNotIn("tool", [message.role for message in messages])
            self.assertTrue(any("Tool observation from read_file" in message.text_content() for message in messages))

    def test_context_history_uses_token_budget_instead_of_message_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            agent.history_token_budget = 256
            agent.state.messages = [
                *[ChatMessage.text("assistant", f"old-{index} " + "x" * 300) for index in range(25)],
                ChatMessage.text("user", "latest request"),
            ]

            messages = agent._messages_for_model()
            history = messages[1:]

            self.assertEqual(history[-1].text_content(), "latest request")
            self.assertLess(len(history), 20)
            self.assertLessEqual(agent._estimate_messages_tokens(history), agent.history_token_budget)

    def test_oversized_latest_tool_unit_is_truncated_without_breaking_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            agent.history_token_budget = 256
            call = ToolCall(id="call_large", name="read_file", arguments={"path": "large.txt"})
            agent.state.messages = [
                ChatMessage(role="assistant", tool_calls=[call]),
                ChatMessage(
                    role="tool",
                    tool_call_id="call_large",
                    tool_name="read_file",
                    content=[TextPart(text="result " + "x" * 4000)],
                ),
            ]

            history = agent._messages_for_model()[1:]

            self.assertEqual([message.role for message in history], ["assistant", "tool"])
            self.assertEqual(history[0].tool_calls[0].id, history[1].tool_call_id)
            self.assertIn("[truncated]", history[1].text_content())
            self.assertLess(agent._estimate_messages_tokens(history), 300)

    def test_oversized_current_user_prompt_is_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            agent.history_token_budget = 256
            prompt = "请完整分析以下输入：" + "细节" * 1000
            agent.state.messages = [ChatMessage.text("user", prompt)]

            history = agent._messages_for_model()[1:]

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].text_content(), prompt)


if __name__ == "__main__":
    unittest.main()
