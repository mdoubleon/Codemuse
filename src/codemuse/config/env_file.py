"""Small, dependency-free loader for local ``.env`` files."""
from __future__ import annotations

import os
from pathlib import Path


TRUST_WORKSPACE_ENV_ENV = "CODEMUSE_TRUST_WORKSPACE_ENV"


def load_env_file(path: Path) -> list[str]:
    """Load missing environment variables from *path* and return their names.

    This intentionally supports only the simple ``KEY=VALUE`` format used by
    CodeMuse. Process environment variables always win over local files.
    """
    if not path.exists():
        return []

    loaded: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_value(value.strip())
        loaded.append(key)
    return loaded


def workspace_env_is_trusted() -> bool:
    """Return whether an explicitly trusted workspace may supply a ``.env`` file."""
    return os.getenv(TRUST_WORKSPACE_ENV_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
