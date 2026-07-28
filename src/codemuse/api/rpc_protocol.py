"""Versioned request and response envelopes for CodeMuse RPC."""
from __future__ import annotations

import json
from typing import Any

from codemuse.api.json_mode import PROTOCOL_VERSION, _json_value


def parse_request(line: str) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON request.") from exc
    if not isinstance(payload, dict):
        raise ValueError("RPC request must be a JSON object.")
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError(f"Unsupported protocol_version; expected {PROTOCOL_VERSION}.")
    if "id" not in payload or not isinstance(payload.get("method"), str) or not payload["method"].strip():
        raise ValueError("RPC request requires id and method.")
    params = payload.get("params", {})
    if params is not None and not isinstance(params, dict):
        raise ValueError("RPC params must be a JSON object.")
    payload["params"] = params or {}
    return payload


def serialize_event(event: Any, request_id: str) -> str:
    return _serialize({"protocol_version": PROTOCOL_VERSION, "id": request_id, "event": _json_value(event)})


def serialize_result(request_id: str, result: Any) -> str:
    return _serialize({"protocol_version": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": _json_value(result)})


def serialize_error(request_id: str, code: str, message: str) -> str:
    return _serialize({"protocol_version": PROTOCOL_VERSION, "id": request_id, "ok": False, "error": {"code": code, "message": message}})


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
