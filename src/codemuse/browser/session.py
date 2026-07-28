"""In-memory tab and navigation state over the guarded static fetcher."""
from __future__ import annotations

from codemuse.browser.models import BrowserLink, BrowserSnapshot, BrowserTab
from codemuse.web_tools.guarded_fetch import GuardedFetcher, WebFetchConfig


class BrowserSession:
    def __init__(self, fetcher: GuardedFetcher | None = None) -> None:
        self.fetcher = fetcher or GuardedFetcher(WebFetchConfig(max_chars=12000))
        self._tabs: dict[str, BrowserTab] = {}
        self._active_tab_id: str | None = None

    def open(self, url: str, *, new_tab: bool = False, label: str = "") -> BrowserSnapshot:
        tab = self._new_tab(label=label) if new_tab or self._active_tab_id is None else self._active_tab()
        return self._navigate(tab, url)

    def click(self, ref: str) -> BrowserSnapshot:
        snapshot = self.snapshot()
        link = next((item for item in snapshot.links if item.ref == ref), None)
        if link is None:
            raise ValueError(f"Unknown browser ref: {ref}")
        return self._navigate(self._active_tab(), link.url)

    def back(self) -> BrowserSnapshot:
        tab = self._active_tab()
        if tab.history_index <= 0:
            raise ValueError("Browser tab has no previous history entry.")
        tab.history_index -= 1
        return self.snapshot()

    def snapshot(self) -> BrowserSnapshot:
        snapshot = self._active_tab().snapshot
        if snapshot is None:
            raise ValueError("Active browser tab has not loaded a page.")
        return snapshot

    def list_tabs(self) -> list[dict]:
        return [{**tab.to_dict(), "active": tab.tab_id == self._active_tab_id} for tab in self._tabs.values()]

    def focus(self, tab_id: str) -> BrowserSnapshot | None:
        if tab_id not in self._tabs:
            raise ValueError(f"Unknown browser tab: {tab_id}")
        self._active_tab_id = tab_id
        return self._tabs[tab_id].snapshot

    def close(self, tab_id: str) -> None:
        if tab_id not in self._tabs:
            raise ValueError(f"Unknown browser tab: {tab_id}")
        del self._tabs[tab_id]
        if self._active_tab_id == tab_id:
            self._active_tab_id = next(iter(self._tabs), None)

    def _navigate(self, tab: BrowserTab, url: str) -> BrowserSnapshot:
        response = self.fetcher.fetch(url)
        links = [BrowserLink(ref=f"link-{index}", text=str(item.get("text") or item.get("url") or ""), url=str(item.get("url") or "")) for index, item in enumerate(response.links, start=1)]
        snapshot = BrowserSnapshot(url=response.url, title=response.title, text=response.text, links=links, status_code=response.status_code, truncated=response.truncated)
        tab.history = tab.history[: tab.history_index + 1]
        tab.history.append(snapshot)
        tab.history_index = len(tab.history) - 1
        return snapshot

    def _new_tab(self, *, label: str = "") -> BrowserTab:
        tab = BrowserTab(label=label)
        self._tabs[tab.tab_id] = tab
        self._active_tab_id = tab.tab_id
        return tab

    def _active_tab(self) -> BrowserTab:
        if self._active_tab_id is None or self._active_tab_id not in self._tabs:
            raise ValueError("No active browser tab.")
        return self._tabs[self._active_tab_id]
