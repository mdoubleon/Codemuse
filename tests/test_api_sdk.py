"""验证 api sdk 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.api import sdk


class ApiSdkTests(unittest.TestCase):
    """ApiSdkTests：组织该功能的单元测试用例。"""
    def test_run_returns_session_payload_and_events(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            payload = sdk.run("list files", root, collect_events=True)
            sessions = sdk.list_sessions(root)

            self.assertTrue(payload["session_id"])
            self.assertTrue(payload["assistant"].startswith("Tool `list_files` returned"))
            self.assertTrue(any(event["type"] == "tool_result" and event.get("tool_name") == "list_files" for event in payload["events"]))
            self.assertEqual(sessions[0]["session_id"], payload["session_id"])

    def test_approval_checkpoint_flow_uses_stored_session(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            pending = sdk.run("remember this sdk keeps runtime hidden behind an api boundary", root, collect_events=True)
            approvals = sdk.list_approvals(root)

            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0]["session_id"], pending["session_id"])

            approved = sdk.approve(root, approvals[0]["approval_id"], collect_events=True)
            checkpoints = sdk.list_checkpoints(root, session_id=pending["session_id"])

            self.assertEqual(approved["session_id"], pending["session_id"])
            self.assertTrue(any(event["type"] == "checkpoint_created" for event in approved["events"]))
            self.assertTrue(checkpoints)


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
