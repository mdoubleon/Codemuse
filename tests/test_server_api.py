"""验证 server api 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.server.http import CodeMuseServer
from codemuse.server.session_manager import WebSessionManager


class ServerApiTests(unittest.TestCase):
    """ServerApiTests：组织该功能的单元测试用例。"""
    def test_session_manager_runs_prompt_and_records_events(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            handle = manager.create_session()

            job_id = handle.prompt("list files")
            completed = _wait_for_event(handle, "prompt_completed")
            events = handle.events_after(0)["events"]

            self.assertEqual(completed["details"]["job_id"], job_id)
            self.assertTrue(any(event["type"] == "tool_result" and event.get("tool_name") == "list_files" for event in events))

    def test_session_manager_handles_approval_and_checkpoint_jobs(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            handle = manager.create_session()

            handle.prompt("remember this runtime owns orchestration boundaries")
            approval_event = _wait_for_event(handle, "approval_required")
            approvals = handle.list_approvals()

            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0]["approval_id"], approval_event["details"]["approval_id"])

            handle.approve(approvals[0]["approval_id"])
            _wait_for_event(handle, "approve_completed")
            events = handle.events_after(0)["events"]

            self.assertTrue(any(event["type"] == "checkpoint_created" for event in events))
            self.assertTrue(any(event["type"] == "tool_result" and event.get("tool_name") == "save_project_memory" for event in events))

    def test_session_manager_filters_approvals_by_session(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            first = manager.create_session()
            second = manager.create_session()

            first.prompt("remember this approval belongs only to the first session")
            approval_event = _wait_for_event(first, "approval_required")
            first_approvals = first.list_approvals()

            self.assertEqual(len(first_approvals), 1)
            self.assertEqual(first_approvals[0]["approval_id"], approval_event["details"]["approval_id"])
            self.assertEqual(second.list_approvals(), [])

    def test_session_manager_lists_and_restores_persisted_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            first_manager = WebSessionManager(default_workspace=root)
            first_handle = first_manager.create_session()

            first_handle.prompt("list files")
            _wait_for_event(first_handle, "prompt_completed")
            session_id = first_handle.session_id

            second_manager = WebSessionManager(default_workspace=root)
            sessions = second_manager.list_sessions()
            restored_handle = second_manager.get_session(session_id)
            restored_events = restored_handle.events_after(0)["events"]

            self.assertTrue(any(item["session_id"] == session_id for item in sessions))
            self.assertTrue(any(event["type"] == "local_user_prompt" and event["message"] == "list files" for event in restored_events))
            self.assertTrue(any(event["type"] == "message" for event in restored_events))

    def test_http_server_exposes_session_prompt_api(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            server = CodeMuseServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                health = _json_request(f"{base}/health")
                created = _json_request(f"{base}/sessions", method="POST", payload={})
                session_id = created["session_id"]
                queued = _json_request(f"{base}/sessions/{session_id}/prompt", method="POST", payload={"prompt": "list files"})

                self.assertTrue(health["ok"])
                self.assertEqual(queued["session_id"], session_id)
                handle = manager.get_session(session_id)
                _wait_for_event(handle, "prompt_completed")
            finally:
                server.shutdown()
                server.server_close()

    def test_http_server_serves_web_ui_and_api_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            server = CodeMuseServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                index = _raw_request(f"{base}/")
                logo = _raw_request(f"{base}/assets/codemuse-logo.png", decode=False)
                health = _json_request(f"{base}/api/health")
                capabilities = _json_request(f"{base}/api/capabilities")
                created = _json_request(f"{base}/api/sessions", method="POST", payload={})
                session_id = created["session_id"]
                queued = _json_request(f"{base}/api/sessions/{session_id}/prompt", method="POST", payload={"prompt": "list files"})

                self.assertIn("<title>CodeMuse</title>", index)
                self.assertTrue(logo.startswith(b"\x89PNG"))
                self.assertTrue(health["ok"])
                self.assertTrue(any(item["name"] == "list_files" for item in capabilities["capabilities"]))
                self.assertEqual(queued["session_id"], session_id)
                handle = manager.get_session(session_id)
                _wait_for_event(handle, "prompt_completed")
            finally:
                server.shutdown()
                server.server_close()

    def test_http_server_exposes_workbench_data_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            server = CodeMuseServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                indexed = _json_request(f"{base}/api/memory/index", method="POST", payload={"max_files": 10})
                memory = _json_request(f"{base}/api/memory/search?query=tiny%20project")
                repo_cache = _json_request(f"{base}/api/repo/cache")
                repo_status = _json_request(f"{base}/api/repo/status")
                report = _json_request(f"{base}/api/reports/latest")

                self.assertGreaterEqual(indexed["index"]["chunk_count"], 1)
                self.assertGreaterEqual(len(memory["hits"]), 1)
                self.assertIn("imports", repo_cache)
                self.assertIn("git", repo_status)
                self.assertIn("exists", report)
            finally:
                server.shutdown()
                server.server_close()

    def test_http_server_exposes_model_config_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            manager = WebSessionManager(default_workspace=root)
            server = CodeMuseServer(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                providers = _json_request(f"{base}/api/models/providers")
                readiness = _json_request(f"{base}/api/models/readiness")
                updated = _json_request(
                    f"{base}/api/config/set",
                    method="POST",
                    payload={"path": "model.provider", "value": "openai_compatible"},
                )
                config = _json_request(f"{base}/api/config")

                self.assertTrue(any(item["name"] == "openai_compatible" for item in providers["providers"]))
                self.assertTrue(any(item["name"] == "fake" for item in readiness["providers"]))
                self.assertEqual(updated["config"]["model"]["provider"], "openai_compatible")
                self.assertEqual(config["config"]["model"]["provider"], "openai_compatible")
            finally:
                server.shutdown()
                server.server_close()


def _wait_for_event(handle, event_type: str, *, timeout: float = 3.0) -> dict:
    """验证该场景下的输入、状态变化和输出是否符合预期。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = handle.events_after(0)["events"]
        for event in reversed(events):
            if event["type"] == event_type:
                return event
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for event: {event_type}")


def _json_request(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    """验证该场景下的输入、状态变化和输出是否符合预期。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _raw_request(url: str, *, decode: bool = True) -> str | bytes:
    with urllib.request.urlopen(url, timeout=3) as response:
        body = response.read()
        return body.decode("utf-8") if decode else body


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text("# Sample\n\nA tiny project.\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
