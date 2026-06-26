"""验证 config manager 相关功能在对外行为上符合预期。"""
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
from codemuse.config.schema import ConfigValidationError


class ConfigManagerTests(unittest.TestCase):
    """ConfigManagerTests：组织该功能的单元测试用例。"""
    def test_project_config_changes_bootstrap_behavior(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_mcp_config(root)
            _write_config(root, {"runtime": {"max_turns": 3}, "capabilities": {"mcp_enabled": False}})

            agent = build_agent(root)

            self.assertEqual(agent.max_turns, 3)
            self.assertNotIn("mcp__demo__echo", agent.tool_registry.names())

    def test_sdk_reads_and_updates_config(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            updated = sdk.set_config_path(root, "runtime.max_turns", 2)
            snapshot = sdk.get_config(root)
            agent = build_agent(root)

            self.assertEqual(updated["config"]["runtime"]["max_turns"], 2)
            self.assertEqual(snapshot["source_map"]["runtime.max_turns"], "project")
            self.assertEqual(agent.max_turns, 2)

    def test_runtime_override_does_not_write_project_config(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            snapshot = sdk.set_runtime_config_path(root, "runtime.max_turns", 4)
            agent = build_agent(root)

            self.assertEqual(snapshot["config"]["runtime"]["max_turns"], 4)
            self.assertEqual(snapshot["project_config"], {})
            self.assertEqual(snapshot["source_map"]["runtime.max_turns"], "runtime")
            self.assertEqual(agent.max_turns, 4)

    def test_unknown_config_path_is_rejected(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            with self.assertRaises(ConfigValidationError):
                sdk.set_config_path(root, "runtime.not_real", 1)


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")


def _write_config(root: Path, payload: dict) -> None:
    """为测试创建所需的本地文件或配置。"""
    config_dir = root / ".codemuse"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_mcp_config(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    payload = {
        "servers": [
            {
                "name": "demo",
                "transport": "mock",
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text from the model.",
                        "response_template": "mock echo: {text}",
                    }
                ],
            }
        ],
    }
    (root / "mcp.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
