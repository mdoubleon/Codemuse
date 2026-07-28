from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.bootstrap import build_agent
from codemuse.api import sdk
from codemuse.config.schema import CodeMuseConfig, ConfigValidationError, config_schema
from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolCall, ToolSpec
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.runtime.lifecycle import ProviderRequestDecision


class RuntimeToolBudgetTests(unittest.TestCase):
    def test_response_tool_calls_are_deduplicated_and_capped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "README.md").write_text("# Demo\nneedle\n", encoding="utf-8")
            (workspace / "docs").mkdir()
            (workspace / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
            (workspace / "nested").mkdir()
            (workspace / "nested" / "item.txt").write_text("item\n", encoding="utf-8")
            calls = [
                ToolCall(id="list-root", name="list_files", arguments={"path": ".", "max_depth": 1}),
                ToolCall(id="list-root-duplicate", name="list_files", arguments={"max_depth": 1, "path": "."}),
                ToolCall(id="read-readme", name="read_file", arguments={"path": "README.md"}),
                ToolCall(id="search-needle", name="search_text", arguments={"query": "needle"}),
                ToolCall(id="list-docs", name="list_files", arguments={"path": "docs", "max_depth": 1}),
                ToolCall(id="list-nested", name="list_files", arguments={"path": "nested", "max_depth": 1}),
            ]
            llm = _RecordingLLM([LLMResponse(tool_calls=calls), LLMResponse(text="Finished.")])
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.llm = llm

            events = agent.prompt("inspect the repository")

            executed = [event for event in events if event.type == "tool_call"]
            self.assertEqual([event.tool_name for event in executed], ["list_files", "read_file", "search_text", "list_files"])
            self.assertEqual(len([event for event in events if event.type == "tool_result"]), 4)
            limited = [event for event in events if event.type == "tool_calls_limited"]
            self.assertEqual(len(limited), 1)
            self.assertEqual(limited[0].details["requested_count"], 6)
            self.assertEqual(limited[0].details["accepted_count"], 4)
            self.assertEqual(limited[0].details["duplicate_count"], 1)
            self.assertEqual(limited[0].details["overflow_count"], 1)
            self.assertEqual(len(llm.calls), 2)
            assistant_calls = next(message.tool_calls for message in llm.calls[1][0] if message.role == "assistant" and message.tool_calls)
            self.assertEqual([call.id for call in assistant_calls], ["list-root", "read-readme", "search-needle", "list-docs"])

    def test_response_tool_call_limit_is_configured_and_validated(self) -> None:
        self.assertEqual(CodeMuseConfig.from_dict({}).runtime.max_tool_calls_per_turn, 4)
        self.assertEqual(CodeMuseConfig.from_dict({}).runtime.max_tool_calls_per_prompt, 8)
        self.assertEqual(
            CodeMuseConfig.from_dict({"runtime": {"max_tool_calls_per_turn": 2}}).runtime.max_tool_calls_per_turn,
            2,
        )
        self.assertEqual(
            CodeMuseConfig.from_dict({"runtime": {"max_tool_calls_per_prompt": 5}}).runtime.max_tool_calls_per_prompt,
            5,
        )
        with self.assertRaises(ConfigValidationError):
            CodeMuseConfig.from_dict({"runtime": {"max_tool_calls_per_turn": 0}})
        with self.assertRaises(ConfigValidationError):
            CodeMuseConfig.from_dict({"runtime": {"max_tool_calls_per_prompt": 65}})
        schema_paths = {field["path"] for field in config_schema()["fields"]}
        self.assertIn("runtime.max_tool_calls_per_turn", schema_paths)
        self.assertIn("runtime.max_tool_calls_per_prompt", schema_paths)

    def test_prompt_tool_call_budget_forces_a_final_no_tool_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "README.md").write_text("# Demo\nneedle\n", encoding="utf-8")
            (workspace / "docs").mkdir()
            (workspace / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
            llm = _RecordingLLM(
                [
                    LLMResponse(
                        tool_calls=[
                            ToolCall(id="list-1", name="list_files", arguments={"path": ".", "max_depth": 1}),
                            ToolCall(id="read-1", name="read_file", arguments={"path": "README.md"}),
                        ]
                    ),
                    LLMResponse(
                        tool_calls=[
                            ToolCall(id="search-1", name="search_text", arguments={"query": "needle"}),
                            ToolCall(id="list-2", name="list_files", arguments={"path": "docs", "max_depth": 1}),
                        ]
                    ),
                    LLMResponse(text="Final answer from the available observations."),
                ]
            )
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.llm = llm
            agent.max_tool_calls_per_turn = 2
            agent.max_tool_calls_per_prompt = 3

            events = agent.prompt("inspect the repository")

            executed = [event for event in events if event.type == "tool_call"]
            self.assertEqual([event.tool_name for event in executed], ["list_files", "read_file", "search_text"])
            self.assertEqual(len(llm.calls), 3)
            self.assertTrue(llm.calls[0][1])
            self.assertTrue(llm.calls[1][1])
            self.assertEqual(llm.calls[2][1], [])
            self.assertIn("tool-use limit", llm.calls[2][0][-1].text_content())
            limited = [event for event in events if event.type == "tool_calls_limited"]
            self.assertEqual(len(limited), 1)
            self.assertEqual(limited[0].details["prompt_tool_calls_used"], 2)
            self.assertEqual(limited[0].details["prompt_budget_overflow_count"], 1)
            self.assertEqual(limited[0].details["accepted_count"], 1)
            self.assertTrue(any(event.type == "message" and event.message == "Final answer from the available observations." for event in events))

    def test_prompt_tool_call_budget_resets_for_the_next_user_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "README.md").write_text("# Demo\n", encoding="utf-8")
            llm = _RecordingLLM(
                [
                    LLMResponse(tool_calls=[ToolCall(id="list-1", name="list_files", arguments={"path": ".", "max_depth": 1})]),
                    LLMResponse(text="First final answer."),
                    LLMResponse(tool_calls=[ToolCall(id="read-1", name="read_file", arguments={"path": "README.md"})]),
                    LLMResponse(text="Second final answer."),
                ]
            )
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.llm = llm
            agent.max_tool_calls_per_prompt = 1

            first_events = agent.prompt("inspect the workspace")
            second_events = agent.prompt("read the README")

            self.assertEqual(len(llm.calls), 4)
            self.assertEqual(llm.calls[1][1], [])
            self.assertEqual(llm.calls[3][1], [])
            self.assertEqual([event.tool_name for event in first_events if event.type == "tool_call"], ["list_files"])
            self.assertEqual([event.tool_name for event in second_events if event.type == "tool_call"], ["read_file"])

    def test_tool_budget_adds_one_final_no_tool_summary_request(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "README.md").write_text("# Demo\n", encoding="utf-8")
            llm = _RecordingLLM(
                [
                    LLMResponse(tool_calls=[ToolCall(id="list-1", name="list_files", arguments={"path": ".", "max_depth": 1})]),
                    LLMResponse(text="The workspace contains README.md."),
                ]
            )
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.max_turns = 1
            agent.llm = llm

            # The final request must remain tool-free even if an integration tries to add tools.
            agent.emitter.on_before_provider_request(
                lambda _event, _state, messages, _tools: ProviderRequestDecision(
                    messages=messages,
                    tools=agent.tool_registry.specs(),
                )
            )

            events = agent.prompt("inspect the workspace")

            self.assertEqual(len(llm.calls), 2)
            self.assertTrue(llm.calls[0][1])
            self.assertEqual(llm.calls[1][1], [])
            self.assertEqual(llm.calls[1][0][-1].role, "system")
            self.assertIn("tool-use limit", llm.calls[1][0][-1].text_content())
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "list_files" for event in events))
            self.assertTrue(any(event.type == "message" and event.message == "The workspace contains README.md." for event in events))

    def test_final_summary_never_executes_tool_calls_returned_by_provider(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "README.md").write_text("# Demo\n", encoding="utf-8")
            llm = _RecordingLLM(
                [
                    LLMResponse(tool_calls=[ToolCall(id="list-1", name="list_files", arguments={"path": ".", "max_depth": 1})]),
                    LLMResponse(tool_calls=[ToolCall(id="read-2", name="read_file", arguments={"path": "README.md"})]),
                ]
            )
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.max_turns = 1
            agent.llm = llm

            events = agent.prompt("inspect the workspace")

            self.assertEqual(len(llm.calls), 2)
            self.assertEqual(llm.calls[1][1], [])
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "read_file" for event in events))
            blocked = [event for event in events if event.type == "tool_error" and event.details.get("reason") == "tool_turn_limit"]
            self.assertEqual(len(blocked), 1)
            self.assertEqual(blocked[0].details["blocked_tool_calls"][0]["name"], "read_file")
            self.assertIn("did not execute", blocked[0].message or "")
            self.assertIn("tool-use limit", agent.state.messages[-1].text_content())


class RuntimeToolsEnabledTests(unittest.TestCase):
    def test_disabled_tools_are_validated_bootstrapped_and_hard_blocked(self) -> None:
        self.assertTrue(CodeMuseConfig.from_dict({}).runtime.tools_enabled)
        self.assertFalse(CodeMuseConfig.from_dict({"runtime": {"tools_enabled": False}}).runtime.tools_enabled)
        with self.assertRaises(ConfigValidationError):
            CodeMuseConfig.from_dict({"runtime": {"tools_enabled": "false"}})
        schema_paths = {field["path"] for field in config_schema()["fields"]}
        self.assertIn("runtime.tools_enabled", schema_paths)

        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            config_dir = workspace / ".codemuse"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps({"runtime": {"tools_enabled": False}}),
                encoding="utf-8",
            )
            llm = _RecordingLLM(
                [LLMResponse(tool_calls=[ToolCall(id="read-1", name="read_file", arguments={"path": "README.md"})])]
            )
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.llm = llm
            agent.emitter.on_before_provider_request(
                lambda _event, _state, messages, _tools: ProviderRequestDecision(
                    messages=messages,
                    tools=agent.tool_registry.specs(),
                )
            )

            events = agent.prompt("read README.md")

            self.assertFalse(agent.tools_enabled)
            self.assertEqual(len(llm.calls), 1)
            self.assertEqual(llm.calls[0][1], [])
            self.assertEqual(llm.calls[0][0][-1].role, "system")
            self.assertIn("Tools are disabled", llm.calls[0][0][-1].text_content())
            self.assertFalse(any(event.type == "tool_call" for event in events))
            self.assertFalse(any(event.type == "tool_result" for event in events))
            blocked = [event for event in events if event.type == "tool_error" and event.details.get("reason") == "tools_disabled"]
            self.assertEqual(len(blocked), 1)
            self.assertEqual(blocked[0].details["blocked_tool_calls"][0]["name"], "read_file")
            self.assertIn("Tools are disabled", agent.state.messages[-1].text_content())

    def test_session_tool_setting_is_applied_when_the_runtime_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            initial = build_agent(workspace)
            sdk.set_session_config_path(workspace, initial.session_id, "runtime.tools_enabled", False)

            restored = build_agent(workspace, session_id=initial.session_id)

            self.assertFalse(restored.tools_enabled)

    def test_disabled_tools_cannot_execute_an_already_approved_call(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            target = workspace / "notes" / "blocked.txt"
            llm = _RecordingLLM(
                [
                    LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="write-1",
                                name="write_file",
                                arguments={
                                    "path": "notes/blocked.txt",
                                    "content": "must not be written",
                                    "create_dirs": True,
                                    "overwrite": True,
                                },
                            )
                        ]
                    ),
                    LLMResponse(text="Tools remain disabled."),
                ]
            )
            agent = build_agent(workspace)
            agent.memory_provider = None
            agent.llm = llm

            initial_events = agent.prompt("write the note")
            approval_id = str(next(event.details["approval_id"] for event in initial_events if event.type == "approval_required"))
            agent.tools_enabled = False

            events = agent.approve(approval_id)

            self.assertFalse(target.exists())
            self.assertEqual(agent.approval_store.load(approval_id).status, "rejected")
            self.assertTrue(any(event.type == "tool_error" and event.details.get("reason") == "tools_disabled" for event in events))
            self.assertEqual(llm.calls[-1][1], [])


class _RecordingLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[ChatMessage], list[ToolSpec]]] = []
        self._info = LLMProviderInfo(provider="test", model="recording")

    @property
    def info(self) -> LLMProviderInfo:
        return self._info

    def complete(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> LLMResponse:
        self.calls.append((list(messages), list(tools)))
        if not self._responses:
            raise AssertionError("Unexpected model call.")
        return self._responses.pop(0)


if __name__ == "__main__":
    unittest.main()
