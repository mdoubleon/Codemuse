"""验证 mcp integration 相关功能在对外行为上符合预期。"""
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


class MCPIntegrationTests(unittest.TestCase):
    """MCPIntegrationTests：组织该功能的单元测试用例。"""
    def test_mock_mcp_tool_is_registered_and_executed_by_runtime(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_mcp_config(root, destructive=False)

            agent = build_agent(root)
            events = agent.prompt("use mcp to echo hello")

            self.assertIn("mcp__demo__echo", agent.tool_registry.names())
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "mcp__demo__echo" for event in events))
            self.assertTrue(any("mock echo:" in (event.message or "") for event in events))

    def test_destructive_mcp_tool_requires_approval(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_mcp_config(root, destructive=True)

            agent = build_agent(root)
            events = agent.prompt("use mcp to echo hello")
            approvals = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0].tool_name, "mcp__demo__echo")

    def test_mcp_status_reports_ready_servers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_mcp_config(root, destructive=False)

            agent = build_agent(root)
            events = agent.prompt("mcp status")
            status_events = [event for event in events if event.type == "tool_result" and event.tool_name == "mcp_status"]

            self.assertEqual(len(status_events), 1)
            report = status_events[0].details["mcp"]
            self.assertEqual(report["ready_count"], 1)
            self.assertEqual(report["servers"][0]["tool_count"], 1)


def _write_mcp_config(root: Path, *, destructive: bool) -> None:
    """为测试创建所需的本地文件或配置。"""
    payload = {
        "settings": {"tool_prefix": "mcp"},
        "servers": [
            {
                "name": "demo",
                "description": "Local mock MCP server for tests.",
                "transport": "mock",
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text from the model.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                        "response_template": "mock echo: {text}",
                        "is_destructive": destructive,
                    }
                ],
            }
        ],
    }
    (root / "mcp.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
