"""验证 llm provider 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.api import sdk
from codemuse.app.bootstrap import build_agent
from codemuse.cli.main import main as cli_main
from codemuse.config.schema import ConfigValidationError
from codemuse.config.schema import CodeMuseConfig
from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolSpec
from codemuse.llm.provider.openai_compatible import OpenAICompatibleProvider


class LLMProviderTests(unittest.TestCase):
    """LLMProviderTests：组织该功能的单元测试用例。"""
    def test_default_agent_uses_fake_provider(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            agent = build_agent(root)

            self.assertEqual(agent.llm.info.provider, "fake")
            self.assertEqual(agent.llm.info.model, "fake-local")
            self.assertFalse(agent.llm.info.is_stub)

    def test_project_config_can_set_fake_model_name(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            _write_config(root, {"model": {"provider": "fake", "model": "fake-custom"}})

            agent = build_agent(root)

            self.assertEqual(agent.llm.info.provider, "fake")
            self.assertEqual(agent.llm.info.model, "fake-custom")

    def test_sdk_lists_known_model_providers(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        providers = {item["name"]: item for item in sdk.list_model_providers()}

        self.assertTrue(providers["fake"]["implemented"])
        self.assertTrue(providers["openai_compatible"]["implemented"])
        self.assertTrue(providers["bailian"]["implemented"])

    def test_cli_lists_model_providers(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            output = _run_cli(["models", "providers"], default_workspace=root)

            self.assertIn("fake  ready", output)
            self.assertIn("openai_compatible  implemented", output)
            self.assertIn("bailian  implemented", output)

    def test_provider_readiness_reports_missing_keys_without_failing(self) -> None:
        """验证 live provider 已实现，但缺 key 时 readiness 明确显示 not ready。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            readiness = {item["name"]: item for item in sdk.list_provider_readiness(root)}

            self.assertTrue(readiness["fake"]["ready"])
            self.assertFalse(readiness["openai_compatible"]["ready"])
            self.assertEqual(readiness["openai_compatible"]["api_key_env"], "OPENAI_API_KEY")

    def test_openai_compatible_provider_parses_text_tool_calls_and_usage(self) -> None:
        """验证 OpenAI-compatible provider 能解析文本、tool_calls 和 usage。"""
        provider = OpenAICompatibleProvider(model="test-model", base_url="https://example.test/v1", api_key_env="TEST_API_KEY")
        response_payload = {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "hello",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "list_files", "arguments": "{\"path\":\".\"}"},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        with patch.dict("os.environ", {"TEST_API_KEY": "secret"}), patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResponse(response_payload),
        ) as urlopen:
            response = provider.complete(
                [ChatMessage.text("user", "list files")],
                [ToolSpec(name="list_files", description="List files", parameters={"type": "object"})],
            )

        self.assertEqual(response.text, "hello")
        self.assertEqual(response.tool_calls[0].name, "list_files")
        self.assertEqual(response.tool_calls[0].arguments["path"], ".")
        self.assertEqual(response.usage["total_tokens"], 15)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")

    def test_unknown_provider_is_rejected_by_config_schema(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with self.assertRaises(ConfigValidationError):
            CodeMuseConfig.from_dict({"model": {"provider": "not-real", "model": "x"}})


def _run_cli(argv: list[str], *, default_workspace: Path) -> str:
    """在测试中执行命令或调用并捕获输出。"""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli_main(argv, default_workspace=default_workspace)
    if code != 0:
        raise AssertionError(f"CLI exited with {code}")
    return buffer.getvalue()


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")


def _write_config(root: Path, payload: dict) -> None:
    """为测试创建所需的本地文件或配置。"""
    config_dir = root / ".codemuse"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
