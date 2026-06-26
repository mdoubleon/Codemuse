"""Tests for repository import planning and blueprint-derived project plans."""
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
from codemuse.tools.project_plan import build_project_plan_from_blueprint
from codemuse.tools.repo_analysis import build_repo_blueprint
from codemuse.tools.repo_git import import_repository, inspect_git_status, list_repo_cache
from codemuse.tools.repo_import import build_repo_import_plan


class RepoImportPlanTests(unittest.TestCase):
    def test_github_source_becomes_non_cloning_import_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            plan = build_repo_import_plan("https://github.com/openai/codex/tree/main", workspace=root)

            self.assertEqual(plan.source_type, "github")
            self.assertEqual(plan.owner, "openai")
            self.assertEqual(plan.name, "codex")
            self.assertEqual(plan.branch, "main")
            self.assertEqual(plan.repo_id, "openai_codex")
            self.assertTrue(plan.requires_network)
            self.assertFalse(plan.import_ready)

    def test_local_source_must_stay_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            plan = build_repo_import_plan(".", workspace=root)

            self.assertEqual(plan.source_type, "local")
            self.assertTrue(plan.import_ready)
            self.assertEqual(Path(plan.local_path), root.resolve())

    def test_outside_local_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside:
            root = Path(raw)

            with self.assertRaises(PermissionError):
                build_repo_import_plan(str(outside), workspace=root)

    def test_project_plan_uses_blueprint_tasks_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            blueprint = build_repo_blueprint(root)

            plan = build_project_plan_from_blueprint(blueprint, goal="add a safe eval runner")

            self.assertEqual(plan.goal, "add a safe eval runner")
            self.assertGreaterEqual(len(plan.tasks), 4)
            self.assertIn("Verify and report", [task.title for task in plan.tasks])
            self.assertTrue(any("run_eval.py" in step for step in plan.verification))

    def test_runtime_can_prepare_repo_import_and_build_project_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            import_payload = sdk.run("github import https://github.com/openai/codex", root, collect_events=True)
            plan_payload = sdk.run("project plan goal: add approval docs", root, collect_events=True)

            self.assertTrue(_has_tool_result(import_payload, "prepare_repo_import"))
            self.assertTrue(_has_tool_result(plan_payload, "build_project_plan"))
            self.assertIn("Repository import plan", import_payload["assistant"])
            self.assertIn("Project plan", plan_payload["assistant"])

    def test_local_repository_import_writes_cache_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source_repo"
            _write_sample_repo(source)

            record = import_repository("source_repo", workspace=root)
            cache = list_repo_cache(root)

            self.assertEqual(record["repo_id"], "source_repo")
            self.assertTrue((root / "imports" / "source_repo" / "README.md").exists())
            self.assertEqual(record["repo_index"]["file_count"], 3)
            self.assertEqual(len(cache), 1)

    def test_runtime_import_repository_uses_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source_repo"
            _write_sample_repo(source)

            payload = sdk.run("import repository source_repo", root, collect_events=True)
            approval = _single_event(payload, "approval_required", "import_repository")
            approved = sdk.approve(root, str(approval["details"]["approval_id"]), session_id=payload["session_id"], collect_events=True)

            self.assertTrue((root / "imports" / "source_repo" / "README.md").exists())
            self.assertTrue(_has_tool_result(approved, "import_repository"))
            self.assertIn("Imported repository", approved["assistant"])

    def test_repo_git_status_handles_non_git_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            snapshot = inspect_git_status(root)

            self.assertFalse(snapshot.is_git_repo)
            self.assertEqual(snapshot.status, [])


def _write_sample_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Sample Agent\n\nA tiny coding agent.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")


def _has_tool_result(payload: dict[str, object], tool_name: str) -> bool:
    return any(
        isinstance(event, dict) and event.get("type") == "tool_result" and event.get("tool_name") == tool_name
        for event in payload.get("events", [])
    )


def _single_event(payload: dict[str, object], event_type: str, tool_name: str) -> dict[str, object]:
    matches = [
        event
        for event in payload.get("events", [])
        if isinstance(event, dict) and event.get("type") == event_type and event.get("tool_name") == tool_name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {event_type}[{tool_name}], got {len(matches)}")
    return matches[0]


if __name__ == "__main__":
    unittest.main()
