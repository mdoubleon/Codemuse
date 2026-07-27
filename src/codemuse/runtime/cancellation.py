"""Shared cancellation primitive for runtime, providers, and subagents."""
from __future__ import annotations

import threading


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise RuntimeError("operation cancelled")


__all__ = ["CancellationToken"]
