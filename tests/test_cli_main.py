"""验证 cli main 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.api import sdk
from codemuse.cli.main import main as cli_main


class CliMainTests(unittest.TestCase):
    """CliMainTests：组织该功能的单元测试用例。"""
    def test_legacy_prompt_mode_still_runs(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            output = _run_cli(["--workspace", str(root), "list files"], default_workspace=root)

            self.assertIn("tool_result[list_files]", output)
            self.assertIn("session_id:", output)

    def test_capabilities_command_lists_tools(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            output = _run_cli(["capabilities", "list", "--workspace", str(root)], default_workspace=root)

            self.assertIn("builtin_tool", output)
            self.assertIn("list_files", output)

    def test_config_command_updates_project_config(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            output = _run_cli(["config", "set", "runtime.max_turns", "2", "--workspace", str(root)], default_workspace=root)
            snapshot = sdk.get_config(root)

            self.assertIn('"max_turns": 2', output)
            self.assertEqual(snapshot["config"]["runtime"]["max_turns"], 2)

    def test_doctor_command_outputs_release_readiness_json(self) -> None:
        """验证 doctor 命令可以输出结构化 release readiness。"""
        output = _run_cli(["doctor", "--json", "--workspace", str(ROOT)], default_workspace=ROOT)
        payload = json.loads(output)

        self.assertEqual(payload["failed"], 0)
        self.assertTrue(payload["release_ready"])
        self.assertIn(payload["status"], {"pass", "warn"})
        self.assertTrue(any(item["id"] == "eval.baseline" for item in payload["checks"]))

    def test_demo_command_runs_packaged_demo(self) -> None:
        """验证 demo run 命令可以完成可展示闭环。"""
        output = _run_cli(["demo", "run", "--no-report"], default_workspace=ROOT)

        self.assertIn("CodeMuse Demo: passed 5/5 steps.", output)
        self.assertIn("approval_write", output)

    def test_memory_commands_index_and_search_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            index_output = _run_cli(["memory", "index", "--workspace", str(root)], default_workspace=root)
            search_output = _run_cli(["memory", "search", "tiny project", "--workspace", str(root)], default_workspace=root)

            self.assertIn("Memory index refreshed", index_output)
            self.assertIn("Indexed Workspace Files", search_output)
            self.assertIn("tiny project", search_output)


def _run_cli(argv: list[str], *, default_workspace: Path) -> str:
    """在测试中执行命令或调用并捕获输出。"""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli_main(argv, default_workspace=default_workspace)
    if code != 0:
        raise AssertionError(f"CLI exited with {code}")
    return buffer.getvalue()


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
