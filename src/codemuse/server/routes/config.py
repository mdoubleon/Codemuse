"""Framework-neutral handlers for CodeMuse configuration routes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.config.manager import get_config_manager


def get_config_payload(workspace: Path) -> dict[str, Any]:
    return get_config_manager(workspace).get_snapshot().to_dict()


def patch_config_payload(workspace: Path, patch: dict[str, Any]) -> dict[str, Any]:
    return get_config_manager(workspace).patch_project_config(patch).to_dict()


def set_config_payload(workspace: Path, path: str, value: Any) -> dict[str, Any]:
    if not path.strip():
        raise ValueError("path is required")
    return get_config_manager(workspace).set_path(path, value).to_dict()


def set_runtime_payload(workspace: Path, path: str, value: Any) -> dict[str, Any]:
    if not path.strip():
        raise ValueError("path is required")
    return get_config_manager(workspace).set_runtime_override(path, value).to_dict()


def clear_runtime_payload(workspace: Path) -> dict[str, Any]:
    return get_config_manager(workspace).clear_runtime_overrides().to_dict()


__all__ = ["clear_runtime_payload", "get_config_payload", "patch_config_payload", "set_config_payload", "set_runtime_payload"]
