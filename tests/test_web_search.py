from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codemuse.app.bootstrap import build_agent
from codemuse.tools.effects import build_tool_effect_preview
from codemuse.web_tools.guarded_fetch import WebFetchResponse
from codemuse.web_tools.providers import DuckDuckGoSearchProvider, MockSearchProvider
from codemuse.web_tools.tools import WebSearchTool


class _SearchFetcher:
    def fetch(self, _url: str) -> WebFetchResponse:
        return WebFetchResponse(
            url="https://html.duckduckgo.com/html/",
            status_code=200,
            text="results",
            links=[
                {"text": "Result One", "url": "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone"},
                {"text": "DuckDuckGo", "url": "https://duckduckgo.com/about"},
            ],
        )


class WebSearchTests(unittest.TestCase):
    def test_duckduckgo_provider_normalizes_static_links(self) -> None:
        provider = DuckDuckGoSearchProvider(fetcher=_SearchFetcher())  # type: ignore[arg-type]
        self.assertEqual(
            [{"title": "Result One", "url": "https://example.com/one", "snippet": ""}],
            provider.search("codemuse", limit=5),
        )

    def test_tool_routes_modes_and_returns_untrusted_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = WebSearchTool(Path(temp), MockSearchProvider()).execute({"query": "agents", "mode": "github", "limit": 3})
            self.assertIn("site:github.com", result.details["routed_query"])
            self.assertEqual("mock", result.details["provider"])
            self.assertTrue(result.details["untrusted_web_content"])
            self.assertFalse(result.details["executed_javascript"])

    def test_runtime_requires_approval_before_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("# Sample\n", encoding="utf-8")
            agent = build_agent(root)
            events = agent.prompt("web search query: coding agents")
            approval = next(event for event in events if event.type == "approval_required")
            self.assertEqual("web_search", approval.tool_name)
            self.assertEqual("web_search", approval.details["effect_preview"]["kind"])
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "web_search" for event in events))

    def test_effect_preview_blocks_empty_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            preview = build_tool_effect_preview(Path(temp), "web_search", {"query": "", "mode": "web"})
            self.assertTrue(preview["blocked"])


if __name__ == "__main__":
    unittest.main()
