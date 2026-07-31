from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.skills_runtime import SkillRuntime
from codemuse.domain.messages import ChatMessage
from codemuse.skills.loader import load_skills, read_skill_body


class SkillLazyLoadingTests(unittest.TestCase):
    def test_discovery_reads_only_bounded_metadata_without_path_read_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            skill_path = _write_large_skill(root)

            with patch.object(Path, "read_text", side_effect=AssertionError("full skill read during discovery")):
                skills = load_skills(root)

            self.assertEqual(skills["large-skill"].description, "A large skill used for lazy loading tests.")
            body, truncated = read_skill_body(skill_path, max_chars=120)
            self.assertTrue(truncated)
            self.assertEqual(len(body), 120)

    def test_body_is_materialized_only_for_an_activated_skill_and_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_large_skill(root)
            runtime = SkillRuntime(root)
            runtime.use_skill("large-skill")
            state = SimpleNamespace(messages=[ChatMessage.text("user", "use a skill")])

            messages = runtime.transform_context(state, list(state.messages))

            injected = messages[0].text_content()
            self.assertIn("[Skill: large-skill]", injected)
            self.assertIn("[skill body truncated]", injected)
            self.assertLess(len(injected), 8_300)


def _write_large_skill(root: Path) -> Path:
    skill_dir = root / "skills" / "large-skill"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        "name: large-skill\n"
        "description: A large skill used for lazy loading tests.\n"
        "---\n\n"
        + ("instruction line for a lazily activated skill\n" * 50_000),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
