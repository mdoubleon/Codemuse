"""验证 blueprint memory 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.tools.repo_analysis import build_repo_blueprint
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.repo_tools import register_repo_tools


class BlueprintMemoryTests(unittest.TestCase):
    """BlueprintMemoryTests：组织该功能的单元测试用例。"""
    def test_build_repo_blueprint_detects_minimal_architecture(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            blueprint = build_repo_blueprint(root)

            self.assertEqual(blueprint.title, "Sample Agent")
            self.assertTrue(any("Agent runtime layer" in item for item in blueprint.minimal_architecture))
            self.assertTrue(any(module.path.endswith("/runtime") for module in blueprint.modules))
            self.assertTrue(any("Python" in item for item in blueprint.tech_stack))

    def test_tools_save_and_search_blueprint_memory(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            registry = ToolRegistry(root)
            register_repo_tools(registry, root)

            saved = registry.execute("save_blueprint_memory", {"path": "."})
            searched = registry.execute("search_blueprint_memory", {"query": "runtime tools", "limit": 3})

            self.assertTrue(saved.success)
            self.assertIn("Saved Memory", saved.content)
            self.assertTrue(searched.success)
            self.assertIn("runtime", searched.content.lower())


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text(
        "# Sample Agent\n\nA tiny coding agent that studies repositories and saves learning memory.\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample-agent"\ndependencies = ["pytest"]\n',
        encoding="utf-8",
    )
    for folder in ["src/sample/app", "src/sample/runtime", "src/sample/tools", "src/sample/storage", "tests"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "src/sample/app/bootstrap.py").write_text("def build_agent():\n    pass\n", encoding="utf-8")
    (root / "src/sample/runtime/runtime.py").write_text("class AgentRuntime:\n    pass\n", encoding="utf-8")
    (root / "src/sample/tools/registry.py").write_text("class ToolRegistry:\n    pass\n", encoding="utf-8")
    (root / "src/sample/storage/sessions.py").write_text("class SessionStore:\n    pass\n", encoding="utf-8")
    (root / "tests/test_runtime.py").write_text("def test_runtime():\n    assert True\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
