"""Stable JSON-lines envelopes for machine clients."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


PROTOCOL_VERSION = "1"


def emit_json_event(event: Any) -> str:
    return _dumps({"protocol_version": PROTOCOL_VERSION, "kind": "event", "event": _json_value(event)})


def emit_json_result(result: Any) -> str:
    return _dumps({"protocol_version": PROTOCOL_VERSION, "kind": "result", "result": _json_value(result)})


def emit_json_error(code: str, message: str) -> str:
    return _dumps({"protocol_version": PROTOCOL_VERSION, "kind": "error", "error": {"code": code, "message": message}})


def events_to_json_lines(events: list[Any], *, result: Any | None = None) -> list[str]:
    lines = [emit_json_event(event) for event in events]
    if result is not None:
        lines.append(emit_json_result(result))
    return lines


def _json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
