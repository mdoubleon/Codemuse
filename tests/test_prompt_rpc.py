from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codemuse.api.json_mode import emit_json_event
from codemuse.api.rpc_mode import dispatch_request, run_stdio_rpc
from codemuse.api.rpc_protocol import parse_request
from codemuse.prompts import load_prompt, load_prompt_templates, prompt_search_paths
from codemuse.runtime.events import AgentEvent


class PromptLoaderTests(unittest.TestCase):
    def test_workspace_prompt_layers_override_lower_priority_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "prompts").mkdir()
            (root / ".codemuse" / "prompts").mkdir(parents=True)
            (root / "prompts" / "review.md").write_text("low", encoding="utf-8")
            (root / ".codemuse" / "prompts" / "review.md").write_text("high", encoding="utf-8")
            (root / "prompts" / "plan.md").write_text("plan", encoding="utf-8")

            self.assertEqual("high", load_prompt("review", root))
            self.assertEqual("plan", load_prompt("plan.md", root))
            self.assertEqual({"review": "high", "plan": "plan"}, load_prompt_templates(root))
            self.assertEqual(root / ".codemuse" / "prompts", prompt_search_paths(root)[0])

    def test_prompt_name_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                load_prompt("../secret", Path(temp))


class RpcProtocolTests(unittest.TestCase):
    def test_protocol_validates_version_and_shape(self) -> None:
        request = parse_request('{"protocol_version":"1","id":7,"method":"list_sessions"}')
        self.assertEqual({}, request["params"])
        with self.assertRaises(ValueError):
            parse_request('{"protocol_version":"2","id":7,"method":"list_sessions"}')
        with self.assertRaises(ValueError):
            parse_request('[]')

    def test_json_mode_serializes_agent_event(self) -> None:
        payload = json.loads(emit_json_event(AgentEvent(type="turn_end", session_id="s1")))
        self.assertEqual("event", payload["kind"])
        self.assertEqual("turn_end", payload["event"]["type"])

    def test_dispatch_uses_public_sdk(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.api.rpc_mode.sdk.list_sessions", return_value=[{"session_id": "s1"}]):
            result = dispatch_request(Path(temp), {"id": "1", "method": "list_sessions", "params": {}})
        self.assertEqual({"sessions": [{"session_id": "s1"}]}, result)

    def test_stdio_continues_after_bad_request(self) -> None:
        source = io.StringIO('{"protocol_version":"9","id":"bad","method":"list_sessions"}\n{"protocol_version":"1","id":"ok","method":"list_sessions"}\n')
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.api.rpc_mode.sdk.list_sessions", return_value=[]):
            run_stdio_rpc(Path(temp), stdin=source, stdout=output)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(lines[0]["ok"])
        self.assertTrue(lines[1]["ok"])
        self.assertEqual("ok", lines[1]["id"])


if __name__ == "__main__":
    unittest.main()
