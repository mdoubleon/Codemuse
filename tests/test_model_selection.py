"""Regression coverage for atomic model provider selection surfaces."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.api import sdk
from codemuse.cli.main import main as cli_main
from codemuse.server.http import CodeMuseServer
from codemuse.server.session_manager import WebSessionManager


class ModelProviderSelectionTests(unittest.TestCase):
    def test_sdk_selects_deepseek_defaults_and_replaces_generation_options(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            sdk.configure_model_provider(
                workspace,
                "openai_compatible",
                model="relay-model",
                base_url="https://relay.example/v1",
                api_key_env="RELAY_API_KEY",
                temperature=0.8,
                max_tokens=1024,
            )

            snapshot = sdk.configure_model_provider(workspace, "deepseek")
            model = snapshot["config"]["model"]
            project = snapshot["project_config"]["model"]

            self.assertEqual(model["provider"], "deepseek")
            self.assertEqual(model["model"], "deepseek-chat")
            self.assertEqual(model["base_url"], "https://api.deepseek.com/v1")
            self.assertEqual(model["api_key_env"], "DEEPSEEK_API_KEY")
            self.assertEqual(model["temperature"], 0.2)
            self.assertIsNone(model["max_tokens"])
            self.assertNotIn("max_tokens", project)

    def test_cli_models_use_persists_custom_openai_compatible_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)

            output = _run_cli(
                [
                    "models",
                    "use",
                    "openai_compatible",
                    "--model",
                    "gpt-5.5",
                    "--base-url",
                    "https://relay.example/v1",
                    "--api-key-env",
                    "CODEMUSE_API_KEY",
                    "--temperature",
                    "0.4",
                    "--max-tokens",
                    "2048",
                    "--json",
                    "--workspace",
                    str(workspace),
                ],
                default_workspace=workspace,
            )
            model = json.loads(output)["config"]["model"]

            self.assertEqual(model["provider"], "openai_compatible")
            self.assertEqual(model["model"], "gpt-5.5")
            self.assertEqual(model["base_url"], "https://relay.example/v1")
            self.assertEqual(model["api_key_env"], "CODEMUSE_API_KEY")
            self.assertEqual(model["temperature"], 0.4)
            self.assertEqual(model["max_tokens"], 2048)

    def test_http_model_selection_is_atomic_and_rejects_raw_key_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            server = CodeMuseServer(("127.0.0.1", 0), WebSessionManager(default_workspace=workspace))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                selected = _json_request(
                    f"{base}/api/models/select",
                    method="POST",
                    payload={
                        "provider": "deepseek",
                        "model": "deepseek-reasoner",
                        "max_tokens": 4096,
                    },
                )

                model = selected["config"]["model"]
                self.assertEqual(model["provider"], "deepseek")
                self.assertEqual(model["model"], "deepseek-reasoner")
                self.assertEqual(model["max_tokens"], 4096)
                self.assertEqual(model["temperature"], 0.2)

                with self.assertRaises(urllib.error.HTTPError) as raised:
                    _json_request(
                        f"{base}/api/models/select",
                        method="POST",
                        payload={"provider": "deepseek", "api_key": "not-an-environment-variable"},
                    )
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_api_key_env_rejects_raw_api_key_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ValueError, "environment variable name"):
                sdk.configure_model_provider(
                    Path(raw),
                    "openai_compatible",
                    api_key_env="sk-this-is-a-raw-key",
                )

            with self.assertRaisesRegex(ValueError, "environment variable name"):
                sdk.set_config_path(
                    Path(raw),
                    "model.api_key_env",
                    "sk-this-is-a-raw-key",
                )


def _run_cli(argv: list[str], *, default_workspace: Path) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli_main(argv, default_workspace=default_workspace)
    if code != 0:
        raise AssertionError(f"CLI exited with {code}")
    return buffer.getvalue()


def _json_request(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
