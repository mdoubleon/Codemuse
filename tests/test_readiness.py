"""Verify release-readiness doctor checks."""
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

from codemuse.diagnostics.readiness import run_readiness, write_readiness_report


class ReadinessTests(unittest.TestCase):
    """ReadinessTests：组织该功能的单元测试用例。"""

    def test_run_readiness_reports_core_project_as_release_warn_only(self) -> None:
        """验证 doctor 能识别当前开源项目文件和核心能力是否就绪。"""
        report = run_readiness(ROOT)

        self.assertEqual(report.failed, 0)
        self.assertTrue(report.release_ready)
        self.assertIn(report.status, {"pass", "warn"})
        check_ids = {check.id for check in report.checks}
        self.assertIn("capabilities.core_catalog", check_ids)
        self.assertIn("eval.baseline", check_ids)

    def test_run_readiness_can_run_compile_web_and_demo_smoke_gates(self) -> None:
        """验证 doctor 的发布 gate 可以实际运行编译、Web/API 和 demo smoke。"""
        report = run_readiness(ROOT, run_compile=True, web_smoke=True, demo_smoke=True)
        statuses = {check.id: check.status for check in report.checks}

        self.assertEqual(statuses["quality.compileall"], "pass")
        self.assertEqual(statuses["web.api_smoke"], "pass")
        self.assertEqual(statuses["demo.packaged"], "pass")
        self.assertEqual(report.failed, 0)

    def test_write_readiness_report_writes_json_and_markdown(self) -> None:
        """验证 release readiness 报告可以落盘给发布流程读取。"""
        report = run_readiness(ROOT)
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)

            json_path, md_path = write_readiness_report(report, output)

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["failed"], 0)
            self.assertTrue(payload["release_ready"])
            self.assertIn("CodeMuse Release Readiness", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
