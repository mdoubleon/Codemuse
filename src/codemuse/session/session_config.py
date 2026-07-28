"""Persistent, validated configuration overrides scoped to one session."""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from codemuse.config.patch import set_path_value


class SessionConfigStore:
    def __init__(self, workspace: Path) -> None:
        self.root = workspace.resolve() / ".data" / "codemuse" / "session-config"
        self._lock = RLock()

    def load(self, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            return {}
        path = self._path(session_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid session config for {session_id}.") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid session config for {session_id}: expected object.")
        return payload

    def save(self, session_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        if not isinstance(data, dict):
            raise ValueError("session config must be an object")
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(session_id)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(path)
        return dict(data)

    def set_path(self, session_id: str, path: str, value: Any) -> dict[str, Any]:
        return self.save(session_id, set_path_value(self.load(session_id), path, value))

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def config_patch(self, session_id: str | None) -> dict[str, Any]:
        payload = self.load(session_id)
        return {key: value for key, value in payload.items() if key in {"model", "runtime", "capabilities"}}

    def set_active_profile(self, session_id: str, profile: str | None) -> dict[str, Any]:
        payload = self.load(session_id)
        if profile:
            payload["active_profile"] = profile
        else:
            payload.pop("active_profile", None)
        return self.save(session_id, payload)

    def _path(self, session_id: str) -> Path:
        safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in session_id)
        return self.root / f"{safe}.json"
