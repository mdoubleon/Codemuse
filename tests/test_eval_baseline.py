"""Verify the deterministic baseline eval runner and CLI entrypoint."""
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

from codemuse.benchmarks.baseline import default_cases, run_baseline
from codemuse.benchmarks.live import compare_providers, write_provider_comparison
from codemuse.benchmarks.report import load_history_entries
from codemuse.cli.main import main as cli_main


class EvalBaselineTests(unittest.TestCase):
    def test_default_baseline_dataset_has_at_least_sixty_unique_cases(self) -> None:
        cases = default_cases()

        self.assertGreaterEqual(len(cases), 60)
        self.assertEqual(len({case.id for case in cases}), len(cases))
        categories = {case.category for case in cases}
        for expected in ["tools", "approval", "safety", "memory", "web", "skills", "extensions", "mcp", "demo"]:
            self.assertIn(expected, categories)

    def test_run_baseline_writes_json_and_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "reports"

            report = run_baseline(
                output_dir=output,
                case_ids=["file_list", "write_approval", "capability_catalog"],
            )

            self.assertEqual(report.total_cases, 3)
            self.assertEqual(report.failed, 0)
            self.assertEqual(report.passed, 3)
            payload = json.loads((output / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["total_cases"], 3)
            self.assertIn("capabilities", payload["category_summary"])
            self.assertIn("proxy_metrics", payload)
            self.assertIn("failure_summary", payload)
            self.assertIn("CodeMuse Baseline Eval Report", (output / "latest.md").read_text(encoding="utf-8"))

    def test_run_baseline_save_history_writes_platform_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "reports"

            run_baseline(
                output_dir=output,
                case_ids=["file_list", "write_approval", "capability_catalog"],
                save_history=True,
            )

            self.assertTrue((output / "history").exists())
            self.assertTrue((output / "index.json").exists())
            self.assertTrue((output / "index.md").exists())
            self.assertTrue((output / "trend.json").exists())
            self.assertTrue((output / "trend.svg").exists())
            self.assertTrue((output / "failures.json").exists())
            self.assertIn("<svg", (output / "trend.svg").read_text(encoding="utf-8"))
            entries = load_history_entries(output)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].total_cases, 3)

    def test_cli_benchmark_run_supports_case_subset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "reports"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = cli_main(
                    [
                        "benchmark",
                        "run",
                        "--output",
                        str(output),
                        "--cases",
                        "file_list,web_private_block",
                    ],
                    default_workspace=ROOT,
                )

            self.assertEqual(code, 0)
            self.assertIn("Passed 2/2 baseline cases.", buffer.getvalue())
            payload = json.loads((output / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["passed"], 2)

    def test_cli_benchmark_history_lists_saved_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "reports"
            run_baseline(output_dir=output, case_ids=["file_list"], save_history=True)
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = cli_main(["benchmark", "history", "--output", str(output)], default_workspace=ROOT)

            self.assertEqual(code, 0)
            self.assertIn("Benchmark history: 1 run(s).", buffer.getvalue())
            self.assertIn("Trend:", buffer.getvalue())

    def test_provider_comparison_writes_reports_without_probe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "reports"

            report = compare_providers(providers=["fake", "openai_compatible"], probe=False)
            json_path, md_path = write_provider_comparison(report, output)

            self.assertEqual(report.total_providers, 2)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["total_providers"], 2)
            self.assertIn("CodeMuse Provider Comparison", md_path.read_text(encoding="utf-8"))

    def test_cli_benchmark_providers_writes_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "reports"
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                code = cli_main(
                    ["benchmark", "providers", "--output", str(output), "--providers", "fake,openai_compatible"],
                    default_workspace=ROOT,
                )

            self.assertEqual(code, 0)
            self.assertIn("Provider comparison:", buffer.getvalue())
            self.assertTrue((output / "providers.json").exists())


if __name__ == "__main__":
    unittest.main()
