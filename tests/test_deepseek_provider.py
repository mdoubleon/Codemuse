"""Tests for the DeepSeek provider adapter."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.domain.messages import ChatMessage
from codemuse.config.manager import get_config_manager
from codemuse.config.schema import CodeMuseConfig
from codemuse.config.schema import ConfigValidationError
from codemuse.llm.registry import create_llm_provider
from codemuse.llm.registry import get_provider_descriptor
from codemuse.llm.registry import list_llm_providers
from codemuse.llm.provider.deepseek import DEFAULT_DEEPSEEK_API_KEY_ENV
from codemuse.llm.provider.deepseek import DEFAULT_DEEPSEEK_BASE_URL
from codemuse.llm.provider.deepseek import DEFAULT_DEEPSEEK_MODEL
from codemuse.llm.provider.deepseek import DEFAULT_DEEPSEEK_TEMPERATURE
from codemuse.llm.provider.deepseek import DeepSeekProvider


class DeepSeekProviderTests(unittest.TestCase):
    def test_deepseek_config_without_model_uses_provider_default(self) -> None:
        config = CodeMuseConfig.from_dict({"model": {"provider": "deepseek"}}).model

        self.assertEqual(config.model, DEFAULT_DEEPSEEK_MODEL)
        self.assertIsInstance(create_llm_provider(config), DeepSeekProvider)

        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            config_dir = workspace / ".codemuse"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps({"model": {"provider": "deepseek"}}),
                encoding="utf-8",
            )
            user_config = workspace / "user-config.json"
            with patch.dict("os.environ", {"CODEMUSE_USER_CONFIG_PATH": str(user_config)}, clear=True):
                effective = get_config_manager(workspace).get_effective_config().model
            with patch.dict(
                "os.environ",
                {
                    "CODEMUSE_USER_CONFIG_PATH": str(user_config),
                    "CODEMUSE_TRUST_WORKSPACE_MODEL_CONFIG": "1",
                },
                clear=True,
            ):
                trusted_effective = get_config_manager(workspace).get_effective_config().model

        self.assertEqual(effective.provider, "fake")
        self.assertEqual(trusted_effective.model, DEFAULT_DEEPSEEK_MODEL)

    def test_schema_and_registry_create_a_configured_deepseek_provider(self) -> None:
        config = CodeMuseConfig.from_dict(
            {
                "model": {
                    "provider": "deepseek",
                    "model": "deepseek-reasoner",
                    "base_url": "https://deepseek.example/v1",
                    "api_key_env": "TEST_DEEPSEEK_KEY",
                    "temperature": 0.6,
                    "max_tokens": 2048,
                }
            }
        ).model

        provider = create_llm_provider(config)
        descriptor = get_provider_descriptor("deepseek")
        providers = {item["name"]: item for item in list_llm_providers()}

        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.info.provider, "deepseek")
        self.assertEqual(provider.info.model, "deepseek-reasoner")
        self.assertEqual(provider.base_url, "https://deepseek.example/v1")
        self.assertEqual(provider.api_key_env, "TEST_DEEPSEEK_KEY")
        self.assertEqual(provider.temperature, 0.6)
        self.assertEqual(provider.max_tokens, 2048)
        self.assertEqual(descriptor.default_model, DEFAULT_DEEPSEEK_MODEL)
        self.assertEqual(providers["deepseek"]["default_base_url"], DEFAULT_DEEPSEEK_BASE_URL)
        self.assertEqual(providers["deepseek"]["default_temperature"], DEFAULT_DEEPSEEK_TEMPERATURE)

    def test_schema_rejects_invalid_optional_request_parameters(self) -> None:
        with self.assertRaisesRegex(ConfigValidationError, "temperature"):
            CodeMuseConfig.from_dict({"model": {"temperature": 2.1}})
        with self.assertRaisesRegex(ConfigValidationError, "max_tokens"):
            CodeMuseConfig.from_dict({"model": {"max_tokens": 0}})

    def test_deepseek_key_environment_is_inferred_without_overriding_codemuse_relay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "secret"}, clear=True):
                model = get_config_manager(workspace).get_effective_config().model

            self.assertEqual(model.provider, "deepseek")
            self.assertEqual(model.model, DEFAULT_DEEPSEEK_MODEL)
            self.assertEqual(model.api_key_env, DEFAULT_DEEPSEEK_API_KEY_ENV)

            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEY": "deepseek-secret",
                    "CODEMUSE_API_KEY": "relay-secret",
                    "CODEMUSE_BASE_URL": "https://relay.example/v1",
                },
                clear=True,
            ):
                relay_model = get_config_manager(workspace).get_effective_config().model

            self.assertEqual(relay_model.provider, "openai_compatible")
            self.assertEqual(relay_model.api_key_env, "CODEMUSE_API_KEY")

    def test_defaults_and_readiness_use_deepseek_identity(self) -> None:
        provider = DeepSeekProvider()

        self.assertEqual(provider.info.provider, "deepseek")
        self.assertEqual(provider.info.model, DEFAULT_DEEPSEEK_MODEL)
        self.assertEqual(provider.base_url, DEFAULT_DEEPSEEK_BASE_URL)
        self.assertEqual(provider.api_key_env, DEFAULT_DEEPSEEK_API_KEY_ENV)

        with patch.dict("os.environ", {}, clear=True):
            missing = provider.readiness()
        self.assertFalse(missing.ready)
        self.assertEqual(missing.provider, "deepseek")
        self.assertIn(DEFAULT_DEEPSEEK_API_KEY_ENV, missing.reason)

        with patch.dict("os.environ", {DEFAULT_DEEPSEEK_API_KEY_ENV: "secret"}, clear=True):
            ready = provider.readiness()
        self.assertTrue(ready.ready)
        self.assertTrue(ready.api_key_present)

    def test_request_payload_includes_defaults_and_custom_limits(self) -> None:
        provider = DeepSeekProvider(api_key_env="TEST_DEEPSEEK_KEY", max_tokens=4096)
        response_payload = {
            "id": "deepseek-test",
            "choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
        }

        with patch.dict("os.environ", {"TEST_DEEPSEEK_KEY": "secret"}), patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResponse(response_payload),
        ) as urlopen:
            response = provider.complete([ChatMessage.text("user", "hello")], [])

        self.assertEqual(response.text, "done")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, f"{DEFAULT_DEEPSEEK_BASE_URL}/chat/completions")
        self.assertEqual(payload["model"], DEFAULT_DEEPSEEK_MODEL)
        self.assertEqual(payload["temperature"], DEFAULT_DEEPSEEK_TEMPERATURE)
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertNotIn("stream", payload)

    def test_optional_parameters_can_use_upstream_defaults(self) -> None:
        provider = DeepSeekProvider(temperature=None, max_tokens=None)

        payload = provider._build_request_payload([ChatMessage.text("user", "hello")], [], stream=True)

        self.assertNotIn("temperature", payload)
        self.assertNotIn("max_tokens", payload)
        self.assertTrue(payload["stream"])

    def test_invalid_parameters_are_rejected_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "temperature"):
            DeepSeekProvider(temperature=2.1)
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            DeepSeekProvider(max_tokens=0)


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
