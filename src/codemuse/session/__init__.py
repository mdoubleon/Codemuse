"""Session configuration and a lazily imported SDK facade."""
from __future__ import annotations

from typing import Any

from codemuse.session.session_config import SessionConfigStore

__all__ = ["SessionClient", "SessionConfigStore"]


def __getattr__(name: str) -> Any:
    if name == "SessionClient":
        from codemuse.session.client import SessionClient

        return SessionClient
    raise AttributeError(name)
