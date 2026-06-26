"""模块说明：CodeMuse 脚本入口，用于启动 CLI 或 HTTP 服务。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.server.http import run_server


def main() -> int:
    """命令行入口，解析参数并返回进程退出码。"""
    parser = argparse.ArgumentParser(description="Run the CodeMuse backend server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", default=str(ROOT))
    args = parser.parse_args()
    workspace = Path(args.workspace)
    _load_env_file(ROOT / ".env")
    if workspace.resolve() != ROOT.resolve():
        _load_env_file(workspace / ".env")
    run_server(host=args.host, port=args.port, workspace=workspace)
    return 0


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a local .env file without overriding process env."""
    if not path.exists():
        return
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
        value = _strip_env_value(value.strip())
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    if loaded:
        print(f"Loaded local env from {path}: {', '.join(sorted(loaded))}")


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
