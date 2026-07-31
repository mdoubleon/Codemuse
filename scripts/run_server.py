"""模块说明：CodeMuse 脚本入口，用于启动 CLI 或 HTTP 服务。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.config.env_file import load_env_file, workspace_env_is_trusted
from codemuse.server.http import run_server


def main() -> int:
    """命令行入口，解析参数并返回进程退出码。"""
    parser = argparse.ArgumentParser(description="Run the CodeMuse backend server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", default=str(ROOT))
    args = parser.parse_args()
    workspace = Path(args.workspace)
    _load_and_report_env(ROOT / ".env")
    if workspace.resolve() != ROOT.resolve() and workspace_env_is_trusted():
        _load_and_report_env(workspace / ".env")
    run_server(host=args.host, port=args.port, workspace=workspace)
    return 0


def _load_and_report_env(path: Path) -> None:
    """Load a local ``.env`` file without exposing any variable values."""
    loaded = load_env_file(path)
    if loaded:
        print(f"Loaded local env from {path}: {', '.join(sorted(loaded))}")


if __name__ == "__main__":
    raise SystemExit(main())
