"""Tool adapters for bounded static browser navigation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.browser.session import BrowserSession
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class BrowserNavigateTool(BaseTool):
    def __init__(self, workspace: Path, session: BrowserSession) -> None:
        super().__init__(workspace)
        self.session = session

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_navigate", description="Open a public URL or follow a link ref in a static, no-JavaScript browser.", parameters={"type": "object", "properties": {"action": {"type": "string", "enum": ["open", "click"]}, "url": {"type": "string"}, "ref": {"type": "string"}, "new_tab": {"type": "boolean"}, "label": {"type": "string"}}, "required": ["action"]}, permission_domain="network", requires_confirmation=True, sensitive=True)

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action") or "")
        if action == "open":
            snapshot = self.session.open(str(arguments.get("url") or ""), new_tab=bool(arguments.get("new_tab")), label=str(arguments.get("label") or ""))
        elif action == "click":
            snapshot = self.session.click(str(arguments.get("ref") or ""))
        else:
            raise ValueError(f"Unsupported browser navigation action: {action}")
        return _snapshot_result(self.spec.name, snapshot)


class BrowserStateTool(BaseTool):
    def __init__(self, workspace: Path, session: BrowserSession) -> None:
        super().__init__(workspace)
        self.session = session

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_state", description="Inspect cached browser tabs/snapshot, go back in cached history, focus, or close a tab.", parameters={"type": "object", "properties": {"action": {"type": "string", "enum": ["snapshot", "tabs", "back", "focus", "close"]}, "tab_id": {"type": "string"}}, "required": ["action"]}, permission_domain="read")

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action") or "")
        if action == "tabs":
            tabs = self.session.list_tabs()
            return ToolResult(tool_name=self.spec.name, content="browser tabs\n" + "\n".join(f"{item['tab_id']} {item['url']}" for item in tabs), details={"tabs": tabs, "executed_javascript": False})
        if action == "snapshot":
            return _snapshot_result(self.spec.name, self.session.snapshot())
        if action == "back":
            return _snapshot_result(self.spec.name, self.session.back())
        if action == "focus":
            snapshot = self.session.focus(str(arguments.get("tab_id") or ""))
            return _snapshot_result(self.spec.name, snapshot) if snapshot else ToolResult(tool_name=self.spec.name, content="Focused empty browser tab.", details={"executed_javascript": False})
        if action == "close":
            tab_id = str(arguments.get("tab_id") or "")
            self.session.close(tab_id)
            return ToolResult(tool_name=self.spec.name, content=f"Closed browser tab: {tab_id}", details={"tab_id": tab_id, "executed_javascript": False})
        raise ValueError(f"Unsupported browser state action: {action}")


def register_browser_tools(registry, workspace: Path, session: BrowserSession | None = None) -> BrowserSession:
    browser_session = session or BrowserSession()
    registry.register(BrowserNavigateTool(workspace, browser_session), category="browser")
    registry.register(BrowserStateTool(workspace, browser_session), category="browser")
    return browser_session


def _snapshot_result(tool_name: str, snapshot) -> ToolResult:
    details = {"snapshot": snapshot.to_dict(), "untrusted_web_content": True, "executed_javascript": False}
    links = "\n".join(f"{link.ref} {link.text}: {link.url}" for link in snapshot.links[:30])
    content = f"browser snapshot: {snapshot.url}\n{snapshot.text}"
    if links:
        content += "\nlinks:\n" + links
    return ToolResult(tool_name=tool_name, content=content[:16000], details=details)
