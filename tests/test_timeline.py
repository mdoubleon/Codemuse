"""验证 timeline 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import io
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


class TimelineTests(unittest.TestCase):
    """TimelineTests：组织该功能的单元测试用例。"""
    def test_runtime_events_are_persisted_to_timeline(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            payload = sdk.run("list files", root)
            events = sdk.list_timeline(root, session_id=payload["session_id"], limit=20)
            event_types = [event["type"] for event in events]

            self.assertIn("agent_start", event_types)
            self.assertIn("tool_result", event_types)
            self.assertIn("agent_end", event_types)
            self.assertTrue(all(event["session_id"] == payload["session_id"] for event in events))

    def test_cli_timeline_show_reads_persisted_events(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            payload = sdk.run("list files", root)

            output = _run_cli(["timeline", "show", "--session", payload["session_id"], "--workspace", str(root)], default_workspace=root)

            self.assertIn("agent_start", output)
            self.assertIn("tool_result[list_files]", output)


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
