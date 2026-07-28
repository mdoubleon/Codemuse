"""Command controller for the dependency-free interactive shell."""
from __future__ import annotations

import json
import shlex
from pathlib import Path

from codemuse.api import sdk
from codemuse.session import SessionClient


class TuiController:
    def __init__(self, workspace: Path, session_id: str | None = None) -> None:
        self.client = SessionClient(workspace, session_id=session_id)
        if session_id is None:
            self.client.new()
        else:
            self.client.resume(session_id)
        self.should_exit = False

    @property
    def session_id(self) -> str:
        return str(self.client.session_id)

    def submit(self, raw: str) -> str:
        text = raw.strip()
        if not text:
            return ""
        if not text.startswith("/"):
            return str(self.client.prompt(text).get("assistant") or "")
        parts = shlex.split(text)
        command = parts[0].lower()
        args = parts[1:]
        if command in {"/quit", "/exit"}:
            self.should_exit = True
            return "Session closed."
        if command == "/new":
            return f"session_id: {self.client.new()}"
        if command == "/resume":
            return f"session_id: {self.client.resume(_required(args, 'session_id'))}"
        if command == "/sessions":
            return _lines(self.client.sessions(), "session_id")
        if command == "/approvals":
            return _lines(self.client.approvals(), "approval_id")
        if command == "/approve":
            return _summary(self.client.approve(_required(args, "approval_id")))
        if command == "/reject":
            return _summary(self.client.reject(_required(args, "approval_id")))
        if command == "/checkpoints":
            return _lines(self.client.checkpoints(), "checkpoint_id")
        if command == "/checkpoint":
            return _summary(self.client.checkpoint(" ".join(args) or "manual checkpoint"))
        if command == "/rewind":
            checkpoint_id = _required(args, "checkpoint_id")
            mode = args[1] if len(args) > 1 else "conversation_and_workspace"
            return _summary(self.client.rewind(checkpoint_id, mode=mode))
        if command == "/learning":
            return self._learning(args)
        if command == "/help":
            return "/new /resume /sessions /approvals /approve /reject /checkpoint /checkpoints /rewind /learning /quit"
        raise ValueError(f"Unknown command: {command}. Use /help.")

    def _learning(self, args: list[str]) -> str:
        action = args[0].lower() if args else "list"
        if action == "list":
            return _lines(sdk.list_learning_candidates(self.client.workspace, status="pending"), "candidate_id")
        candidate_id = _required(args[1:], "candidate_id")
        if action == "approve":
            return json.dumps(sdk.approve_learning_candidate(self.client.workspace, candidate_id), ensure_ascii=False)
        if action == "reject":
            return json.dumps(sdk.reject_learning_candidate(self.client.workspace, candidate_id), ensure_ascii=False)
        raise ValueError("Usage: /learning [list|approve <id>|reject <id>]")


def _required(args: list[str], name: str) -> str:
    if not args or not args[0].strip():
        raise ValueError(f"Missing required argument: {name}")
    return args[0]


def _summary(payload: dict) -> str:
    return f"session_id: {payload.get('session_id', '')} assistant: {payload.get('assistant', '')}".strip()


def _lines(items: list[dict], identifier: str) -> str:
    if not items:
        return "No items."
    return "\n".join(f"{item.get(identifier, '')}  {item.get('title') or item.get('tool_name') or item.get('updated_at') or ''}".rstrip() for item in items)
