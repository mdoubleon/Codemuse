"""Verify the packaged deterministic demo."""
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

from codemuse.demo.runner import run_demo


class DemoTests(unittest.TestCase):
    """DemoTests：组织该功能的单元测试用例。"""

    def test_run_demo_passes_all_packaged_steps(self) -> None:
        """验证五分钟 demo 的核心步骤全部可运行。"""
        report = run_demo(save_report=False)

        self.assertEqual(report.failed, 0)
        self.assertEqual(report.passed, report.total_steps)
        self.assertEqual(report.total_steps, 5)

    def test_run_demo_writes_json_and_markdown_report(self) -> None:
        """验证 demo 报告可以写给展示和 CI 读取。"""
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            report = run_demo(output_dir=output)

            payload = json.loads((output / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["total_steps"], report.total_steps)
            self.assertIn("CodeMuse Demo Report", (output / "latest.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

