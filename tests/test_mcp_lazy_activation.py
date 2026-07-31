from __future__ import annotations

import json
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.bootstrap import build_agent
from codemuse.domain.tools import ToolCall
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.mcp.config import MCPServerConfig
from codemuse.mcp.session import StdioMCPClient


class _SequencedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._info = LLMProviderInfo(provider="test", model="mcp-lazy")

    @property
    def info(self) -> LLMProviderInfo:
        return self._info

    def complete(self, _messages, _tools) -> LLMResponse:
        if not self._responses:
            raise AssertionError("Unexpected provider call")
        return self._responses.pop(0)


class MCPLazyActivationTests(unittest.TestCase):
    def test_lazy_stdio_server_is_never_started_by_bootstrap_or_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_stdio_config(root)

            with patch("codemuse.mcp.session.StdioMCPClient") as client_type:
                agent = build_agent(root)
                self.assertIn("mcp_status", agent.tool_registry.names())
                self.assertIn("mcp_activate", agent.tool_registry.names())
                self.assertNotIn("mcp__untrusted__echo", agent.tool_registry.names())

                result = agent.tool_registry.execute("mcp_status", {})

            client_type.assert_not_called()
            report = result.details["mcp"]
            self.assertEqual(report["ready_count"], 0)
            self.assertEqual(report["active_count"], 0)
            self.assertEqual(report["servers"][0]["status"], "configured")
            self.assertTrue(report["servers"][0]["activation_required"])

    def test_approval_is_required_before_external_activation_and_registers_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_stdio_config(root)
            responses = [
                LLMResponse(tool_calls=[ToolCall(id="activate", name="mcp_activate", arguments={"server": "untrusted"})]),
                LLMResponse(text="activation complete"),
            ]

            with patch("codemuse.mcp.session.StdioMCPClient") as client_type:
                client = client_type.return_value
                client.list_tools.return_value = [
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
                agent = build_agent(root)
                agent.memory_provider = None
                agent.llm = _SequencedLLM(responses)

                staged = agent.prompt("activate the configured MCP server")
                approvals = [event for event in staged if event.type == "approval_required"]

                self.assertEqual(len(approvals), 1)
                approval_id = approvals[0].details["approval_id"]
                self.assertTrue(approvals[0].details["exact_effect_approval"])
                self.assertTrue(approvals[0].details["effect_digest"])
                self.assertEqual(approvals[0].details["effect_preview"]["command"], "not-a-real-mcp-command")
                client_type.assert_not_called()

                completed = agent.approve(approval_id)

            self.assertTrue(client_type.called)
            self.assertTrue(any(event.type == "approval_completed" for event in completed))
            self.assertIn("mcp__untrusted__echo", agent.tool_registry.names())
            status = agent.tool_registry.execute("mcp_status", {}).details["mcp"]
            self.assertEqual(status["active_count"], 1)
            self.assertTrue(status["servers"][0]["active"])

    def test_activation_is_stale_when_the_configured_external_effect_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_stdio_config(root)
            responses = [
                LLMResponse(tool_calls=[ToolCall(id="activate", name="mcp_activate", arguments={"server": "untrusted"})]),
                LLMResponse(text="activation was not executed"),
            ]
            with patch("codemuse.mcp.session.StdioMCPClient") as client_type:
                agent = build_agent(root)
                agent.memory_provider = None
                agent.llm = _SequencedLLM(responses)
                staged = agent.prompt("activate the configured MCP server")
                approval_id = next(event.details["approval_id"] for event in staged if event.type == "approval_required")
                config_path = root / "mcp.json"
                payload = json.loads(config_path.read_text(encoding="utf-8"))
                payload["servers"][0]["command"] = "changed-after-review"
                config_path.write_text(json.dumps(payload), encoding="utf-8")

                events = agent.approve(str(approval_id))

            self.assertTrue(any(event.type == "approval_stale" for event in events))
            client_type.assert_not_called()

    def test_activation_uses_config_current_when_the_plan_was_created(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_stdio_config(root)
            responses = [
                LLMResponse(tool_calls=[ToolCall(id="activate", name="mcp_activate", arguments={"server": "untrusted"})]),
                LLMResponse(text="activation complete"),
            ]
            with patch("codemuse.mcp.session.StdioMCPClient") as client_type:
                client = client_type.return_value
                client.list_tools.return_value = []
                agent = build_agent(root)
                _rewrite_stdio_command(root, "changed-before-plan")
                agent.memory_provider = None
                agent.llm = _SequencedLLM(responses)

                staged = agent.prompt("activate the configured MCP server")
                approval = next(event for event in staged if event.type == "approval_required")
                self.assertEqual("changed-before-plan", approval.details["effect_preview"]["command"])
                agent.approve(str(approval.details["approval_id"]))

            started_server = client_type.call_args.args[0]
            self.assertEqual("changed-before-plan", started_server.command)

    def test_duplicate_mcp_server_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_stdio_config(root)
            config_path = root / "mcp.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["servers"].append(dict(payload["servers"][0]))
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Duplicate MCP server name: untrusted"):
                build_agent(root)

    def test_stdio_request_timeout_is_bounded_even_when_stdout_never_returns_a_line(self) -> None:
        class _BlockingStdout:
            def __init__(self) -> None:
                self.release = threading.Event()

            def readline(self) -> bytes:
                self.release.wait(5)
                return b""

        class _Process:
            def __init__(self) -> None:
                self.stdout = _BlockingStdout()
                self.stdin = io.BytesIO()

            def poll(self):
                return None

            def terminate(self) -> None:
                self.stdout.release.set()

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                self.stdout.release.set()

        process = _Process()
        server = MCPServerConfig(name="blocked", transport="stdio", command="blocked", timeout_seconds=1)
        with patch("codemuse.mcp.session.subprocess.Popen", return_value=process):
            client = StdioMCPClient(server)
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                client._request("tools/list", {})
            elapsed = time.monotonic() - started
            client.close()

        self.assertLess(elapsed, 1.5)


def _write_stdio_config(root: Path) -> None:
    payload = {
        "settings": {"tool_prefix": "mcp", "lifecycle": "lazy"},
        "servers": [
            {
                "name": "untrusted",
                "transport": "stdio",
                "command": "not-a-real-mcp-command",
                "tools": [
                    {
                        "name": "echo",
                        "description": "Declared but not callable before activation.",
                        "input_schema": {"type": "object"},
                    }
                ],
            }
        ],
    }
    (root / "mcp.json").write_text(json.dumps(payload), encoding="utf-8")


def _rewrite_stdio_command(root: Path, command: str) -> None:
    config_path = root / "mcp.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["servers"][0]["command"] = command
    config_path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
