"""预留浏览器自动化能力的包入口。"""
"""Bounded static browser with tab state and guarded navigation."""

from codemuse.browser.models import BrowserLink, BrowserSnapshot, BrowserTab
from codemuse.browser.session import BrowserSession
from codemuse.browser.tools import BrowserNavigateTool, BrowserStateTool, register_browser_tools

__all__ = ["BrowserLink", "BrowserNavigateTool", "BrowserSession", "BrowserSnapshot", "BrowserStateTool", "BrowserTab", "register_browser_tools"]
