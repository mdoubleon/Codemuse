"""Capability inventory assembled from config and discovery providers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.app.bootstrap import create_capability_catalog
from codemuse.config.manager import config_for_workspace


def capability_inventory(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    config = config_for_workspace(workspace)
    items = [item.to_dict() for item in create_capability_catalog(workspace).list()]
    counts: dict[str, int] = {}
    for item in items:
        kind = str(item.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return {"workspace": str(workspace), "settings": config.capabilities.to_dict(), "counts": counts, "capabilities": items}


__all__ = ["capability_inventory"]
