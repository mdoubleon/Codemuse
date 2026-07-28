"""Register guarded static fetch and public-search tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.tools.base import BaseTool, ToolResult, ToolSpec
from codemuse.tools.effects import build_web_fetch_effect_preview
from codemuse.web_tools.guarded_fetch import GuardedFetchError, GuardedFetcher, WebFetchConfig
from codemuse.web_tools.providers import DuckDuckGoSearchProvider, SearchProvider


class WebFetchTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_fetch",
            description="Fetch a public http/https URL as readable text without executing JavaScript.",
            parameters={"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}, "timeout_seconds": {"type": "integer"}}, "required": ["url"]},
            permission_domain="network",
            requires_confirmation=True,
            sensitive=True,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        preview = build_web_fetch_effect_preview(self.workspace, arguments)
        if preview.get("blocked"):
            return ToolResult(tool_name=self.spec.name, content=f"web_fetch blocked: {preview.get('reason')}", is_error=True, details={"effect_preview": preview})
        config = WebFetchConfig(
            timeout_seconds=int(preview["timeout_seconds"]),
            max_chars=int(preview["max_chars"]),
            max_bytes=int(preview["max_bytes"]),
            max_redirects=int(preview["max_redirects"]),
            allow_private_network=bool(preview["allow_private_network"]),
        )
        try:
            response = GuardedFetcher(config).fetch(str(preview["url"]))
        except GuardedFetchError as exc:
            return ToolResult(tool_name=self.spec.name, content=f"web_fetch error: {exc}", is_error=True, details={"url": preview["url"], "error": str(exc), "executed_javascript": False})
        return ToolResult(
            tool_name=self.spec.name,
            content=f"web_fetch: {response.url}\n{response.text}".strip(),
            details={"url": response.url, "status_code": response.status_code, "content_type": response.content_type, "text": response.text, "redirects": response.redirects, "truncated": response.truncated, "executed_javascript": response.executed_javascript},
        )


class WebSearchTool(BaseTool):
    def __init__(self, workspace: Path, provider: SearchProvider | None = None) -> None:
        super().__init__(workspace)
        self.provider = provider or DuckDuckGoSearchProvider()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description="Search the public web, recent news, or GitHub-oriented results with a static no-JavaScript provider.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}, "mode": {"type": "string", "enum": ["web", "news", "github"]}, "limit": {"type": "integer"}}, "required": ["query"]},
            permission_domain="network",
            requires_confirmation=True,
            sensitive=True,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("web_search requires query")
        mode = str(arguments.get("mode") or "web")
        if mode not in {"web", "news", "github"}:
            raise ValueError(f"Unsupported web_search mode: {mode}")
        limit = max(1, min(10, int(arguments.get("limit") or 5)))
        routed_query = query
        if mode == "news":
            routed_query = f"{query} latest news"
        elif mode == "github":
            routed_query = f"site:github.com {query} repository"
        results = self.provider.search(routed_query, limit=limit)
        content = "\n".join(f"{item.get('title', '')} - {item.get('url', '')}\n{item.get('snippet', '')}".strip() for item in results) or "No web search results."
        return ToolResult(tool_name=self.spec.name, content=content, details={"query": query, "routed_query": routed_query, "mode": mode, "provider": self.provider.name, "results": results, "result_count": len(results), "freshness": "static", "executed_javascript": False, "untrusted_web_content": True})


def register_web_tools(registry, workspace: Path, search_provider: SearchProvider | None = None) -> None:
    registry.register(WebFetchTool(workspace), category="web")
    registry.register(WebSearchTool(workspace, search_provider), category="web")
