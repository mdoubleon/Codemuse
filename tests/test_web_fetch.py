"""验证 guarded web fetch 的安全边界和工具接入。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.bootstrap import build_agent
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.web_tools.guarded_fetch import GuardedFetchError, GuardedFetcher, WebFetchConfig, WebFetchResponse, readable_text, validate_url


class WebFetchTests(unittest.TestCase):
    """WebFetchTests：组织 guarded fetch 相关测试。"""

    def test_validate_url_blocks_private_address(self) -> None:
        """验证私有地址会被 SSRF 防护拦截。"""
        with self.assertRaises(GuardedFetchError):
            validate_url("http://127.0.0.1:8000")

    def test_readable_text_removes_script_and_tags(self) -> None:
        """验证 HTML 会被抽取成不执行脚本的可读文本。"""
        text = readable_text("<html><script>alert(1)</script><body><h1>Hello</h1><p>World</p></body></html>")

        self.assertEqual(text, "Hello World")

    def test_guarded_fetch_truncates_response_text(self) -> None:
        """验证静态 fetch 会按 max_chars 截断正文。"""
        opener = _FakeOpener("<html><body>" + ("a" * 50) + "</body></html>")
        fetcher = GuardedFetcher(WebFetchConfig(max_chars=12, allow_private_network=True), opener=opener)

        response = fetcher.fetch("https://example.com/page")

        self.assertEqual(response.text, "aaaaaaaaaaaa")
        self.assertTrue(response.truncated)
        self.assertFalse(response.executed_javascript)

    def test_web_fetch_requires_approval_and_fetches_after_approval(self) -> None:
        """验证 web_fetch 先进入审批，批准后才访问网页。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            with patch("codemuse.web_tools.guarded_fetch.resolve_addresses", return_value=["93.184.216.34"]):
                agent = build_agent(root)
                events = agent.prompt("web fetch url: https://example.com/page max_chars=500")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "web_fetch" for event in events))
            preview = approval_events[0].details["effect_preview"]
            self.assertEqual(preview["kind"], "web_fetch")
            self.assertEqual(preview["url"], "https://example.com/page")
            self.assertFalse(preview["blocked"])

            with patch("codemuse.web_tools.guarded_fetch.resolve_addresses", return_value=["93.184.216.34"]):
                with patch("codemuse.web_tools.tools.GuardedFetcher", _FakeFetcher):
                    approved_events = agent.approve(str(approval_events[0].details["approval_id"]))

            tool_results = [event for event in approved_events if event.type == "tool_result" and event.tool_name == "web_fetch"]
            self.assertEqual(len(tool_results), 1)
            self.assertIn("Fetched page", tool_results[0].message or "")
            self.assertTrue(any(event.type == "checkpoint_created" and event.tool_name == "web_fetch" for event in approved_events))

    def test_web_fetch_blocks_private_url_even_if_approved(self) -> None:
        """验证私有地址即使被 approve，也不会发起网络请求。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            agent = build_agent(root)
            events = agent.prompt("web fetch url: http://127.0.0.1:8000/secret")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            self.assertTrue(approval_events[0].details["effect_preview"]["blocked"])

            approved_events = agent.approve(str(approval_events[0].details["approval_id"]))
            pending = PendingApprovalStore(root / ".data" / "codemuse" / "approvals").load(str(approval_events[0].details["approval_id"]))

            self.assertEqual(pending.status, "stale")
            self.assertTrue(any(event.type == "approval_stale" and event.tool_name == "web_fetch" for event in approved_events))
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "web_fetch" for event in approved_events))


@dataclass
class _FakeResponse:
    """模拟 urllib response。"""

    body: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "text/html; charset=utf-8"})

    def read(self, _size: int) -> bytes:
        """返回 fake 响应正文。"""
        return self.body.encode("utf-8")


class _FakeOpener:
    """模拟 urllib opener。"""

    def __init__(self, body: str) -> None:
        self.body = body

    def open(self, _request, timeout: int):  # noqa: ANN001
        """返回 fake HTTP 响应。"""
        return _FakeResponse(self.body)


class _FakeFetcher:
    """模拟 GuardedFetcher，避免测试访问真实网络。"""

    def __init__(self, _config: WebFetchConfig) -> None:
        pass

    def fetch(self, url: str) -> WebFetchResponse:
        """返回固定网页内容。"""
        return WebFetchResponse(url=url, status_code=200, text="Fetched page", content_type="text/html")


def _write_sample_repo(root: Path) -> None:
    """为测试创建最小 workspace。"""
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
