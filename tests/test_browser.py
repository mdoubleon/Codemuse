from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codemuse.browser.session import BrowserSession
from codemuse.browser.tools import register_browser_tools
from codemuse.tools.policy import ALLOW, ASK, ToolPolicyEvaluator
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.effects import build_tool_effect_preview
from codemuse.web_tools.guarded_fetch import GuardedFetcher, WebFetchConfig, WebFetchResponse


class _Fetcher:
    def fetch(self, url: str) -> WebFetchResponse:
        links = [{"text": "Next", "url": "https://example.com/next"}] if url.endswith("start") else []
        return WebFetchResponse(url=url, status_code=200, text=f"page {url}", title="Example", links=links)


class BrowserTests(unittest.TestCase):
    def test_fetcher_extracts_title_and_links(self) -> None:
        class Opener:
            def open(self, _request, timeout):
                class Response:
                    status = 200
                    headers = {"content-type": "text/html; charset=utf-8"}
                    def read(self, _size):
                        return b'<html><title>Docs</title><body><a href="/next">Next page</a></body></html>'
                return Response()
        response = GuardedFetcher(WebFetchConfig(allow_private_network=True), opener=Opener()).fetch("https://example.com/start")
        self.assertEqual("Docs", response.title)
        self.assertEqual("https://example.com/next", response.links[0]["url"])
        self.assertFalse(response.executed_javascript)

    def test_tabs_click_and_cached_back(self) -> None:
        session = BrowserSession(fetcher=_Fetcher())  # type: ignore[arg-type]
        first = session.open("https://example.com/start")
        second = session.click(first.links[0].ref)
        self.assertTrue(second.url.endswith("next"))
        self.assertTrue(session.back().url.endswith("start"))
        session.open("https://example.org/start", new_tab=True)
        self.assertEqual(2, len(session.list_tabs()))

    def test_navigation_requires_approval_but_cached_state_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry = ToolRegistry(Path(temp))
            register_browser_tools(registry, Path(temp), BrowserSession(fetcher=_Fetcher()))  # type: ignore[arg-type]
            policy = ToolPolicyEvaluator()
            self.assertEqual(ASK, policy.evaluate(registry.get_spec("browser_navigate")).action)
            self.assertEqual(ALLOW, policy.evaluate(registry.get_spec("browser_state")).action)
            opened = registry.execute("browser_navigate", {"action": "open", "url": "https://example.com/start"})
            self.assertFalse(opened.details["executed_javascript"])
            snapshot = registry.execute("browser_state", {"action": "snapshot"})
            self.assertIn("link-1", snapshot.content)

    def test_navigation_effect_preview_validates_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            blocked = build_tool_effect_preview(Path(temp), "browser_navigate", {"action": "open", "url": "http://127.0.0.1/"})
            self.assertTrue(blocked["blocked"])
            self.assertEqual("browser_navigate", blocked["kind"])


if __name__ == "__main__":
    unittest.main()
