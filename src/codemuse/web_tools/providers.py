"""Small provider layer for guarded, static public-web search."""
from __future__ import annotations

from typing import Protocol
from urllib.parse import parse_qs, quote_plus, urlparse

from codemuse.web_tools.guarded_fetch import GuardedFetcher, WebFetchConfig


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]: ...


class MockSearchProvider:
    name = "mock"

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        return [{"title": f"Mock result for {query}", "url": "https://example.com/", "snippet": "Static mock search result."}][:limit]


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self, *, timeout_seconds: int = 10, fetcher: GuardedFetcher | None = None) -> None:
        self.fetcher = fetcher or GuardedFetcher(WebFetchConfig(timeout_seconds=timeout_seconds, max_chars=20000, max_bytes=512000))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        response = self.fetcher.fetch(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in response.links:
            title = " ".join(str(link.get("text") or "").split())
            url = _unwrap_duckduckgo_url(str(link.get("url") or ""))
            host = (urlparse(url).hostname or "").lower()
            if not title or not url or "duckduckgo.com" in host or url in seen:
                continue
            seen.add(url)
            results.append({"title": title, "url": url, "snippet": ""})
            if len(results) >= max(1, limit):
                break
        return results


def _unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" not in (parsed.hostname or "").lower():
        return url
    target = parse_qs(parsed.query).get("uddg", [])
    return target[0] if target else url
