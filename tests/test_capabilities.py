"""验证 capabilities 相关功能在对外行为上符合预期。"""
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

from codemuse.api import sdk
from codemuse.app.bootstrap import create_capability_catalog


class CapabilityCatalogTests(unittest.TestCase):
    """CapabilityCatalogTests：组织该功能的单元测试用例。"""
    def test_catalog_lists_builtin_and_subagent_capabilities(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            catalog = create_capability_catalog(root)
            names = {item.name for item in catalog.list()}

            self.assertIn("list_files", names)
            self.assertIn("run_shell", names)
            self.assertIn("web_fetch", names)
            self.assertIn("spawn_subagent", names)
            self.assertIn("run_skill", names)
            self.assertIn("run_extension", names)
            self.assertEqual(catalog.get("builtin_tool", "list_files").metadata["permission_domain"], "read")
            self.assertEqual(catalog.get("builtin_tool", "run_shell").metadata["permission_domain"], "shell")
            self.assertTrue(catalog.get("builtin_tool", "run_shell").metadata["requires_confirmation"])
            self.assertEqual(catalog.get("web_tool", "web_fetch").metadata["permission_domain"], "network")
            self.assertTrue(catalog.get("web_tool", "web_fetch").metadata["requires_confirmation"])
            self.assertEqual(catalog.get("repo_tool", "prepare_repo_import").metadata["permission_domain"], "read")
            self.assertEqual(catalog.get("repo_tool", "build_project_plan").metadata["category"], "repo")
            self.assertEqual(catalog.get("skill", "run_skill").metadata["permission_domain"], "read")
            self.assertEqual(catalog.get("extension", "run_extension").metadata["permission_domain"], "read")

    def test_catalog_includes_mcp_tools_when_enabled(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_mcp_config(root)

            capabilities = sdk.list_capabilities(root, kind="mcp_tool")

            names = {item["name"] for item in capabilities}
            self.assertIn("mcp__demo__echo", names)
            self.assertIn("mcp_status", names)

    def test_catalog_respects_config_disabled_mcp(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_mcp_config(root)
            _write_config(root, {"capabilities": {"mcp_enabled": False}})

            capabilities = sdk.list_capabilities(root)
            names = {item["name"] for item in capabilities}

            self.assertNotIn("mcp__demo__echo", names)

    def test_catalog_respects_config_disabled_web(self) -> None:
        """验证 web_enabled=false 时不注册 web_fetch。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_config(root, {"capabilities": {"web_enabled": False}})

            capabilities = sdk.list_capabilities(root)
            names = {item["name"] for item in capabilities}

            self.assertNotIn("web_fetch", names)

    def test_catalog_includes_workspace_skills_and_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_skill(root)
            _write_extension(root)

            capabilities = sdk.list_capabilities(root)
            by_key = {(item["kind"], item["name"]): item for item in capabilities}

            self.assertIn(("skill", "experiment-report"), by_key)
            self.assertEqual(by_key[("skill", "experiment-report")]["metadata"]["source"], "project")
            self.assertEqual(by_key[("skill", "experiment-report")]["status"], "loaded")
            self.assertIn(("extension", "project-extension"), by_key)
            self.assertIn(("extension", "extension__project_extension__summarize"), by_key)
            self.assertEqual(by_key[("extension", "project-extension")]["risk_level"], "medium")
            self.assertEqual(by_key[("extension", "project-extension")]["metadata"]["provides"], ["tool", "hook"])
            self.assertEqual(by_key[("extension", "project-extension")]["metadata"]["execution"], "manifest_runtime")
            self.assertEqual(by_key[("extension", "project-extension")]["metadata"]["runtime_tool"], "run_extension")

    def test_skill_runtime_tool_executes_discovered_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_skill(root)

            payload = sdk.run("run skill name: experiment-report for eval summary", root, collect_events=True)
            tool_names = [
                event.get("tool_name")
                for event in payload["events"]
                if isinstance(event, dict) and event.get("type") == "tool_result"
            ]

            self.assertIn("run_skill", tool_names)
            self.assertIn("Skill runtime result", payload["assistant"])
            self.assertIn("experiment-report", payload["assistant"])

    def test_extension_runtime_tool_executes_manifest_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_extension(root)

            payload = sdk.run("run extension name: project-extension with eval input", root, collect_events=True)
            tool_names = [
                event.get("tool_name")
                for event in payload["events"]
                if isinstance(event, dict) and event.get("type") == "tool_result"
            ]

            self.assertIn("run_extension", tool_names)
            self.assertIn("Extension runtime result", payload["assistant"])
            self.assertIn("project-extension", payload["assistant"])

    def test_dynamic_extension_tool_executes_manifest_declared_tool(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_extension(root)

            payload = sdk.run("extension tool summarize this input", root, collect_events=True)
            tool_names = [
                event.get("tool_name")
                for event in payload["events"]
                if isinstance(event, dict) and event.get("type") == "tool_result"
            ]

            self.assertIn("extension__project_extension__summarize", tool_names)
            self.assertIn("dynamic summary", payload["assistant"])

    def test_catalog_respects_config_disabled_skills_and_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_skill(root)
            _write_extension(root)
            _write_config(root, {"capabilities": {"skills_enabled": False, "extensions_enabled": False}})

            capabilities = sdk.list_capabilities(root)
            keys = {(item["kind"], item["name"]) for item in capabilities}

            self.assertNotIn(("skill", "experiment-report"), keys)
            self.assertNotIn(("extension", "project-extension"), keys)


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")


def _write_mcp_config(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    payload = {
        "servers": [
            {
                "name": "demo",
                "transport": "mock",
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text from the model.",
                        "response_template": "mock echo: {text}",
                    }
                ],
            }
        ],
    }
    (root / "mcp.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_skill(root: Path) -> None:
    skill_dir = root / "skills" / "experiment-report"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: experiment-report\ndescription: Build experiment reports from inputs.\n---\n\n# Body\n",
        encoding="utf-8",
    )


def _write_extension(root: Path) -> None:
    extension_dir = root / "extensions" / "project-extension"
    extension_dir.mkdir(parents=True)
    payload = {
        "name": "project-extension",
        "description": "Adds project-specific runtime hooks.",
        "version": "0.1.0",
        "entrypoint": "extension.py",
        "provides": ["tool", "hook"],
        "response_template": "Extension {name} handled {action}: {input}",
        "tools": [
            {
                "name": "summarize",
                "description": "Summarize input through the project extension.",
                "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}},
                "response_template": "dynamic summary from {name}: {input}",
            }
        ],
    }
    (extension_dir / "EXTENSION.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_config(root: Path, payload: dict) -> None:
    """为测试创建所需的本地文件或配置。"""
    config_dir = root / ".codemuse"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
