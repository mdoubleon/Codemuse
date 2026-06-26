"""验证 tool registry 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.tools.file_tools import ListFilesTool
from codemuse.tools.registry import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    """ToolRegistryTests：组织该功能的单元测试用例。"""
    def test_register_lists_metadata_and_payloads(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            registry = ToolRegistry(root)
            registry.register(ListFilesTool(root), category="coding")

            self.assertEqual(registry.names(), ["list_files"])
            self.assertEqual(registry.list_tools()[0]["category"], "coding")
            self.assertEqual(registry.spec_payloads()[0]["name"], "list_files")
            self.assertFalse(registry.spec_payloads()[0]["side_effect"])

    def test_duplicate_registration_is_rejected(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            registry = ToolRegistry(root)
            registry.register(ListFilesTool(root))

            with self.assertRaises(ValueError):
                registry.register(ListFilesTool(root))

    def test_tool_result_becomes_tool_chat_message(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            registry = ToolRegistry(root)
            registry.register(ListFilesTool(root))

            result = registry.execute("list_files", {"path": ".", "max_depth": 1})
            message = result.as_chat_message()

            self.assertEqual(message.role, "tool")
            self.assertEqual(message.tool_name, "list_files")
            self.assertTrue(message.metadata["success"])
            self.assertIn("README.md", message.text_content())


if __name__ == "__main__":
    unittest.main()
