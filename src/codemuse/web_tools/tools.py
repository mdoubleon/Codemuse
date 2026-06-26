"""把受保护的网页获取能力注册成 Agent 工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.tools.base import BaseTool, ToolResult, ToolSpec
from codemuse.tools.effects import build_web_fetch_effect_preview
from codemuse.web_tools.guarded_fetch import GuardedFetchError, GuardedFetcher, WebFetchConfig


class WebFetchTool(BaseTool):
    """静态获取网页内容的网络工具，执行前必须经过审批。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 web_fetch 的 URL、超时、大小限制和网络权限域。"""
        return ToolSpec(
            name="web_fetch",
            description="Fetch a public http/https URL as readable text without executing JavaScript.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer"},
                    "timeout_seconds": {"type": "integer"},
                },
                "required": ["url"],
            },
            permission_domain="network",
            requires_confirmation=True,
            sensitive=True,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """审批通过后执行静态网页获取，并返回可读文本和元数据。"""
        preview = build_web_fetch_effect_preview(self.workspace, arguments)
        if preview.get("blocked"):
            return ToolResult(
                tool_name=self.spec.name,
                content=f"web_fetch blocked: {preview.get('reason')}",
                is_error=True,
                details={"effect_preview": preview},
            )
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
            return ToolResult(
                tool_name=self.spec.name,
                content=f"web_fetch error: {exc}",
                is_error=True,
                details={
                    "url": preview["url"],
                    "error": str(exc),
                    "executed_javascript": False,
                },
            )
        content = f"web_fetch: {response.url}\n{response.text}".strip()
        return ToolResult(
            tool_name=self.spec.name,
            content=content,
            details={
                "url": response.url,
                "status_code": response.status_code,
                "content_type": response.content_type,
                "text": response.text,
                "redirects": response.redirects,
                "truncated": response.truncated,
                "executed_javascript": response.executed_javascript,
            },
        )


def register_web_tools(registry, workspace: Path) -> None:
    """把 Web 工具注册到 ToolRegistry。"""
    registry.register(WebFetchTool(workspace), category="web")
