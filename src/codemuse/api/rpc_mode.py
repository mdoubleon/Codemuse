"""Synchronous JSON-lines RPC dispatcher for CodeMuse SDK operations."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO

from codemuse.api import sdk
from codemuse.api.rpc_protocol import parse_request, serialize_error, serialize_event, serialize_result


def run_stdio_rpc(workspace: Path, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    for raw_line in input_stream:
        if not raw_line.strip():
            continue
        request_id = "unknown"
        try:
            request = parse_request(raw_line)
            request_id = str(request["id"])
            result = dispatch_request(workspace.resolve(), request, output_stream)
            _write(output_stream, serialize_result(request_id, result))
        except (KeyError, TypeError, ValueError, FileNotFoundError) as exc:
            _write(output_stream, serialize_error(request_id, "invalid_request", str(exc)))
        except Exception as exc:  # noqa: BLE001 - the protocol must isolate failed requests
            _write(output_stream, serialize_error(request_id, "internal_error", str(exc)))


def dispatch_request(workspace: Path, request: dict[str, Any], output_stream: TextIO | None = None) -> Any:
    method = str(request["method"])
    params = dict(request.get("params") or {})
    request_id = str(request["id"])

    def emit(event: Any) -> None:
        if output_stream is not None:
            _write(output_stream, serialize_event(event, request_id))

    if method == "run":
        return sdk.run(str(params.get("prompt") or ""), workspace, session_id=params.get("session_id"), subscriber=emit)
    if method == "approve":
        return sdk.approve(workspace, str(params["approval_id"]), session_id=params.get("session_id"), subscriber=emit)
    if method == "reject":
        return sdk.reject(workspace, str(params["approval_id"]), session_id=params.get("session_id"), subscriber=emit)
    if method == "enqueue_message":
        return sdk.enqueue_message(workspace, str(params.get("text") or ""), session_id=params.get("session_id"), delivery=str(params.get("delivery") or "follow_up"))
    if method == "compact_session":
        return sdk.compact_session(workspace, session_id=params.get("session_id"))
    if method == "list_sessions":
        return {"sessions": sdk.list_sessions(workspace)}
    if method == "list_session_tree":
        return {"sessions": sdk.list_session_tree(workspace)}
    if method == "fork_session":
        return sdk.fork_session(workspace, str(params["session_id"]))
    if method == "create_checkpoint":
        return sdk.create_checkpoint(workspace, session_id=params.get("session_id"), label=str(params.get("label") or "manual checkpoint"), subscriber=emit)
    if method == "list_checkpoints":
        return {"checkpoints": sdk.list_checkpoints(workspace, session_id=params.get("session_id"))}
    if method == "preview_rewind":
        return sdk.preview_rewind(workspace, str(params["checkpoint_id"]), session_id=params.get("session_id"), mode=str(params.get("mode") or "conversation_and_workspace"))
    if method == "rewind":
        return sdk.rewind(workspace, str(params["checkpoint_id"]), session_id=params.get("session_id"), mode=str(params.get("mode") or "conversation_and_workspace"), subscriber=emit)
    if method == "list_approvals":
        return {"approvals": sdk.list_approvals(workspace, status=params.get("status", "pending"))}
    if method == "list_learning_candidates":
        return {"candidates": sdk.list_learning_candidates(workspace, status=params.get("status"))}
    if method == "approve_learning_candidate":
        return sdk.approve_learning_candidate(workspace, str(params["candidate_id"]))
    if method == "reject_learning_candidate":
        return sdk.reject_learning_candidate(workspace, str(params["candidate_id"]))
    if method == "list_capabilities":
        return {"capabilities": sdk.list_capabilities(workspace, kind=params.get("kind"))}
    if method == "list_mcp_resources":
        return {"resources": sdk.list_mcp_resources(workspace)}
    if method == "read_mcp_resource":
        return sdk.read_mcp_resource(workspace, str(params["server_name"]), str(params["uri"]))
    if method == "list_mcp_prompts":
        return {"prompts": sdk.list_mcp_prompts(workspace)}
    if method == "get_mcp_prompt":
        return sdk.get_mcp_prompt(workspace, str(params["server_name"]), str(params["name"]), dict(params.get("arguments") or {}))
    if method == "get_config":
        return sdk.get_config(workspace)
    if method == "patch_config":
        return sdk.patch_config(workspace, dict(params.get("patch") or {}))
    if method == "set_config":
        return sdk.set_config_path(workspace, str(params.get("path") or ""), params.get("value"))
    if method == "set_runtime_config":
        return sdk.set_runtime_config_path(workspace, str(params.get("path") or ""), params.get("value"))
    if method == "clear_runtime_config":
        return sdk.clear_runtime_config(workspace)
    if method == "get_session_config":
        return sdk.get_session_config(workspace, str(params["session_id"]))
    if method == "set_session_config":
        return sdk.set_session_config_path(workspace, str(params["session_id"]), str(params["path"]), params.get("value"))
    if method == "clear_session_config":
        return sdk.clear_session_config(workspace, str(params["session_id"]))
    raise ValueError(f"Unsupported RPC method: {method}")


def _write(stream: TextIO, line: str) -> None:
    stream.write(line + "\n")
    stream.flush()
