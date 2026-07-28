"""Stateful SDK facade for clients that operate one session at a time."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.api import sdk


class SessionClient:
    def __init__(self, workspace: Path, session_id: str | None = None) -> None:
        self.workspace = workspace.resolve()
        self.session_id = session_id

    def new(self) -> str:
        self.session_id = sdk.create_runtime(self.workspace).session_id
        return self.session_id

    def resume(self, session_id: str) -> str:
        self.session_id = sdk.create_runtime(self.workspace, session_id=session_id).session_id
        return self.session_id

    def prompt(self, text: str, *, collect_events: bool = False) -> dict[str, Any]:
        payload = sdk.run(text, self.workspace, session_id=self.session_id, collect_events=collect_events)
        self.session_id = str(payload["session_id"])
        return payload

    def enqueue(self, text: str, *, delivery: str = "follow_up") -> dict[str, Any]:
        payload = sdk.enqueue_message(self.workspace, text, session_id=self.session_id, delivery=delivery)
        self.session_id = str(payload["session_id"])
        return payload

    def approve(self, approval_id: str, *, collect_events: bool = False) -> dict[str, Any]:
        payload = sdk.approve(self.workspace, approval_id, session_id=self.session_id, collect_events=collect_events)
        self.session_id = str(payload["session_id"])
        return payload

    def reject(self, approval_id: str, *, collect_events: bool = False) -> dict[str, Any]:
        payload = sdk.reject(self.workspace, approval_id, session_id=self.session_id, collect_events=collect_events)
        self.session_id = str(payload["session_id"])
        return payload

    def checkpoint(self, label: str = "manual checkpoint") -> dict[str, Any]:
        payload = sdk.create_checkpoint(self.workspace, session_id=self.session_id, label=label)
        self.session_id = str(payload["session_id"])
        return payload

    def rewind(self, checkpoint_id: str, *, mode: str = "conversation_and_workspace") -> dict[str, Any]:
        payload = sdk.rewind(self.workspace, checkpoint_id, session_id=self.session_id, mode=mode)
        self.session_id = str(payload["session_id"])
        return payload

    def sessions(self) -> list[dict[str, Any]]:
        return sdk.list_sessions(self.workspace)

    def approvals(self) -> list[dict[str, Any]]:
        return sdk.list_approvals(self.workspace)

    def checkpoints(self) -> list[dict[str, Any]]:
        return sdk.list_checkpoints(self.workspace, session_id=self.session_id)
