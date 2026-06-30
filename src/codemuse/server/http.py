"""实现标准库 HTTP API，把请求路由到 WebSessionManager。"""
from __future__ import annotations

import json
import mimetypes
from importlib import resources
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from codemuse.api import sdk
from codemuse.app.bootstrap import create_capability_catalog
from codemuse.server.session_manager import WebSessionManager
from codemuse.tools.repo_git import inspect_git_status, list_repo_cache

_STATIC_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}


class CodeMuseServer(ThreadingHTTPServer):
    """携带 WebSessionManager 的线程化 HTTP Server。"""
    def __init__(self, server_address: tuple[str, int], manager: WebSessionManager) -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        super().__init__(server_address, CodeMuseRequestHandler)
        self.manager = manager


class CodeMuseRequestHandler(BaseHTTPRequestHandler):
    # HTTP 层只负责解析请求、返回 JSON；真正的 Agent 执行仍交给 WebSessionManager 和 Runtime。
    """处理静态资源、REST API、会话事件和审批请求。"""
    server: CodeMuseServer

    def do_GET(self) -> None:
        """处理 HTTP GET 请求，主要用于 health、session 列表和事件查询。"""
        parsed = urlparse(self.path)
        static_asset = _static_asset_name(parsed.path)
        if static_asset:
            self._send_static(static_asset)
            return
        parts = _api_path_parts(parsed.path)
        try:
            if parts == ["health"]:
                self._send_json({"ok": True, "workspace": str(self.server.manager.default_workspace)})
                return
            if parts == ["capabilities"]:
                query = parse_qs(parsed.query)
                kind = _string_query(query, "kind", default="")
                catalog = create_capability_catalog(self.server.manager.default_workspace)
                self._send_json({"capabilities": [item.to_dict() for item in catalog.list(kind=kind or None)]})
                return
            if parts == ["config"]:
                self._send_json(sdk.get_config(self.server.manager.default_workspace))
                return
            if parts == ["models", "providers"]:
                self._send_json({"providers": sdk.list_model_providers()})
                return
            if parts == ["models", "readiness"]:
                self._send_json({"providers": sdk.list_provider_readiness(self.server.manager.default_workspace)})
                return
            if parts == ["memory", "search"]:
                query = parse_qs(parsed.query)
                text = _string_query(query, "query", default="")
                limit = _int_query(query, "limit", default=6)
                self._send_json(sdk.search_memory(self.server.manager.default_workspace, text, limit=limit))
                return
            if parts == ["repo", "cache"]:
                self._send_json({"imports": list_repo_cache(self.server.manager.default_workspace)})
                return
            if parts == ["repo", "status"]:
                query = parse_qs(parsed.query)
                raw_path = _string_query(query, "path", default=".")
                target = _resolve_workspace_path(self.server.manager.default_workspace, raw_path)
                snapshot = inspect_git_status(target, include_diff=_bool_query(query, "include_diff", default=False))
                self._send_json({"git": snapshot.to_dict()})
                return
            if parts == ["reports", "latest"]:
                self._send_json(_latest_report_payload(self.server.manager.default_workspace))
                return
            if parts == ["sessions"]:
                self._send_json({"sessions": self.server.manager.list_sessions()})
                return
            if len(parts) == 2 and parts[0] == "sessions":
                handle = self.server.manager.get_session(parts[1])
                self._send_json(handle.snapshot())
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "events":
                cursor = _int_query(parse_qs(parsed.query), "after", default=0)
                handle = self.server.manager.get_session(parts[1])
                self._send_json(handle.events_after(cursor))
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "approvals":
                query = parse_qs(parsed.query)
                status = _string_query(query, "status", default="pending")
                handle = self.server.manager.get_session(parts[1])
                self._send_json({"approvals": handle.list_approvals(status=status or None)})
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "checkpoints":
                handle = self.server.manager.get_session(parts[1])
                self._send_json({"checkpoints": handle.list_checkpoints()})
                return
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001 - HTTP boundary converts failures to JSON
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        """处理 HTTP POST 请求，把 prompt、approval、checkpoint 等操作路由到 SessionHandle。"""
        parts = _api_path_parts(urlparse(self.path).path)
        payload = self._read_json()
        if payload is None:
            return
        try:
            if parts == ["sessions"]:
                workspace_value = str(payload.get("workspace") or "").strip()
                workspace = Path(workspace_value) if workspace_value else None
                handle = self.server.manager.create_session(workspace=workspace)
                self._send_json({"session_id": handle.session_id}, status=HTTPStatus.CREATED)
                return
            if parts == ["memory", "index"]:
                max_files = int(payload.get("max_files") or 300)
                self._send_json(sdk.refresh_memory(self.server.manager.default_workspace, max_files=max_files), status=HTTPStatus.ACCEPTED)
                return
            if parts == ["config", "set"]:
                path = str(payload.get("path") or "").strip()
                if not path:
                    raise ValueError("path is required.")
                self._send_json(sdk.set_config_path(self.server.manager.default_workspace, path, payload.get("value")))
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "prompt":
                prompt = str(payload.get("prompt") or "")
                handle = self.server.manager.get_session(parts[1])
                job_id = handle.prompt(prompt)
                self._send_json({"session_id": handle.session_id, "job_id": job_id}, status=HTTPStatus.ACCEPTED)
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "approve":
                approval_id = str(payload.get("approval_id") or "")
                if not approval_id:
                    raise ValueError("approval_id is required.")
                handle = self.server.manager.get_session(parts[1])
                job_id = handle.approve(approval_id)
                self._send_json({"session_id": handle.session_id, "job_id": job_id}, status=HTTPStatus.ACCEPTED)
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "reject":
                approval_id = str(payload.get("approval_id") or "")
                if not approval_id:
                    raise ValueError("approval_id is required.")
                handle = self.server.manager.get_session(parts[1])
                job_id = handle.reject(approval_id)
                self._send_json({"session_id": handle.session_id, "job_id": job_id}, status=HTTPStatus.ACCEPTED)
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "checkpoint":
                label = str(payload.get("label") or "manual checkpoint")
                handle = self.server.manager.get_session(parts[1])
                job_id = handle.checkpoint(label)
                self._send_json({"session_id": handle.session_id, "job_id": job_id}, status=HTTPStatus.ACCEPTED)
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "rewind":
                checkpoint_id = str(payload.get("checkpoint_id") or "")
                if not checkpoint_id:
                    raise ValueError("checkpoint_id is required.")
                handle = self.server.manager.get_session(parts[1])
                job_id = handle.rewind(checkpoint_id)
                self._send_json({"session_id": handle.session_id, "job_id": job_id}, status=HTTPStatus.ACCEPTED)
                return
            if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "cancel":
                handle = self.server.manager.get_session(parts[1])
                result = handle.cancel()
                self._send_json({"session_id": handle.session_id, **result}, status=HTTPStatus.ACCEPTED)
                return
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - HTTP boundary converts failures to JSON
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_OPTIONS(self) -> None:
        """响应 CORS preflight 请求，便于未来 Web UI 调用。"""
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """关闭默认 HTTP 访问日志，避免测试和 CLI 输出噪声。"""
        return

    def _read_json(self) -> dict | None:
        """读取 HTTP 请求体并解析成 JSON 对象。"""
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON body must be an object."}, status=HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def _send_json(self, payload: dict, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        """把字典序列化为 UTF-8 JSON 响应并写回客户端。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, asset_name: str) -> None:
        """返回打包在 codemuse.web.static 中的前端静态资源。"""
        try:
            body = resources.files("codemuse.web.static").joinpath(asset_name).read_bytes()
        except FileNotFoundError:
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(asset_name)[0] or "application/octet-stream"
        if asset_name.endswith(".js"):
            content_type = "text/javascript"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def run_server(*, host: str, port: int, workspace: Path) -> None:
    """创建 WebSessionManager 和 HTTP server，并开始阻塞监听。"""
    manager = WebSessionManager(default_workspace=workspace)
    server = CodeMuseServer((host, port), manager)
    print(f"CodeMuse backend listening on http://{host}:{port}")
    server.serve_forever()


def _path_parts(path: str) -> list[str]:
    """按 URL 路径切分非空片段。"""
    return [part for part in path.split("/") if part]


def _api_path_parts(path: str) -> list[str]:
    """处理 APIpathparts。"""
    parts = _path_parts(path)
    if parts and parts[0] == "api":
        return parts[1:]
    return parts


def _static_asset_name(path: str) -> str:
    """处理 staticasset名称。"""
    if path.startswith("/assets/"):
        asset = path.removeprefix("/assets/")
        if asset and "/" not in asset and "\\" not in asset:
            return f"assets/{asset}"
    return _STATIC_ROUTES.get(path, "")


def _int_query(query: dict[str, list[str]], name: str, *, default: int) -> int:
    """从 query string 中读取整数参数，解析失败时返回默认值。"""
    values = query.get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except ValueError:
        return default


def _string_query(query: dict[str, list[str]], name: str, *, default: str) -> str:
    """从 query string 中读取字符串参数，缺失时返回默认值。"""
    values = query.get(name)
    if not values:
        return default
    return values[0]


def _bool_query(query: dict[str, list[str]], name: str, *, default: bool) -> bool:
    """处理 boolquery。"""
    values = query.get(name)
    if not values:
        return default
    return values[0].lower() in {"1", "true", "yes", "on"}


def _resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    """解析工作区path。"""
    candidate = Path(raw_path or ".")
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    root = workspace.resolve()
    if root not in resolved.parents and resolved != root:
        raise PermissionError(f"Path is outside workspace: {raw_path}")
    return resolved


def _latest_report_payload(workspace: Path) -> dict[str, object]:
    """处理 latest报告载荷。"""
    report = workspace / "evals" / "reports" / "latest.json"
    failures = workspace / "evals" / "reports" / "failures.json"
    payload: dict[str, object] = {"exists": report.exists(), "report": None, "failures": None}
    if report.exists():
        payload["report"] = json.loads(report.read_text(encoding="utf-8"))
    if failures.exists():
        payload["failures"] = json.loads(failures.read_text(encoding="utf-8"))
    return payload
