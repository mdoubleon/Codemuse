"""验证 memory context 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.domain.messages import ChatMessage
from codemuse.memory.blueprint_memory import BlueprintStore
from codemuse.memory.index_pipeline import refresh_memory_index, search_memory_pipeline
from codemuse.memory.retrieval_hook import MEMORY_RECALL_METADATA_KEY, MemoryContextProvider
from codemuse.tools.repo_analysis import blueprint_to_memory_items, build_repo_blueprint


class MemoryContextTests(unittest.TestCase):
    """MemoryContextTests：组织该功能的单元测试用例。"""
    def test_provider_inserts_recalled_memory_message(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _save_sample_blueprint_memory(root)
            provider = MemoryContextProvider(root)

            messages = [
                ChatMessage.text("system", "You are CodeMuse."),
                ChatMessage.text("user", "How should I design runtime tools?"),
            ]
            transformed = provider.transform_context(state=None, messages=messages)

            self.assertEqual(transformed[0].role, "system")
            self.assertEqual(transformed[1].role, "system")
            self.assertIn(MEMORY_RECALL_METADATA_KEY, transformed[1].metadata)
            self.assertIn("runtime", transformed[1].text_content().lower())

    def test_fake_llm_can_use_injected_memory_context(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _save_sample_blueprint_memory(root)
            provider = MemoryContextProvider(root)

            messages = provider.transform_context(
                state=None,
                messages=[
                    ChatMessage.text("system", "You are CodeMuse."),
                    ChatMessage.text("user", "How should I design runtime tools?"),
                ],
            )

            from codemuse.llm.fake import FakeLLM

            response = FakeLLM().complete(messages, tools=[])

            self.assertIn("relevant memory", response.text.lower())
            self.assertIn("runtime", response.text.lower())

    def test_memory_index_pipeline_searches_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            report = refresh_memory_index(root)
            result = search_memory_pipeline(root, "ToolRegistry runtime", limit=3)

            self.assertGreaterEqual(report.index.chunk_count, 1)
            self.assertGreaterEqual(len(result.hits), 1)
            self.assertTrue(any("ToolRegistry" in hit.content for hit in result.hits))

    def test_provider_can_recall_indexed_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            refresh_memory_index(root)
            provider = MemoryContextProvider(root)

            messages = [
                ChatMessage.text("system", "You are CodeMuse."),
                ChatMessage.text("user", "Where is ToolRegistry mentioned?"),
            ]
            transformed = provider.transform_context(state=None, messages=messages)

            self.assertEqual(transformed[1].role, "system")
            self.assertIn(MEMORY_RECALL_METADATA_KEY, transformed[1].metadata)
            self.assertIn("ToolRegistry", transformed[1].text_content())


def _save_sample_blueprint_memory(root: Path) -> None:
    """验证该场景下的输入、状态变化和输出是否符合预期。"""
    blueprint = build_repo_blueprint(root)
    store = BlueprintStore(root / ".data" / "codemuse" / "blueprint_memory")
    store.save_blueprint(blueprint)
    store.save_memory_items(blueprint_to_memory_items(blueprint))


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text(
        "# Sample Agent\n\nA tiny agent with runtime and tools modules.\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "sample-agent"\n',
        encoding="utf-8",
    )
    for folder in ["src/sample/runtime", "src/sample/tools", "src/sample/storage"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "src/sample/runtime/runtime.py").write_text("class AgentRuntime:\n    pass\n", encoding="utf-8")
    (root / "src/sample/tools/registry.py").write_text("class ToolRegistry:\n    pass\n", encoding="utf-8")
    (root / "src/sample/storage/sessions.py").write_text("class SessionStore:\n    pass\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
