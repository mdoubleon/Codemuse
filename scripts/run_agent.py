"""模块说明：CodeMuse 脚本入口，用于启动 CLI 或 HTTP 服务。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.cli.main import main as cli_main
from codemuse.config.env_file import load_env_file


def main(argv: list[str] | None = None) -> int:
    """Load local environment files before dispatching the CodeMuse CLI."""
    args = list(sys.argv[1:] if argv is None else argv)
    _load_local_env(args)
    return cli_main(args, default_workspace=ROOT)


def _load_local_env(argv: list[str]) -> None:
    """Match server startup: ``.env`` augments, never overrides, process env."""
    workspace = _workspace_from_args(argv)
    paths = [ROOT / ".env"]
    if workspace != ROOT:
        paths.append(workspace / ".env")
    for path in paths:
        load_env_file(path)


def _workspace_from_args(argv: list[str]) -> Path:
    """Read the optional workspace flag without duplicating CLI argument parsing."""
    for index, token in enumerate(argv):
        if token.startswith("--workspace="):
            return Path(token.split("=", 1)[1]).expanduser().resolve()
        if token in {"--workspace", "-w"} and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser().resolve()
    return ROOT


if __name__ == "__main__":
    # 脚本只负责设置源码路径和默认 workspace；真正的 CLI 解析在 codemuse.cli.main。
    raise SystemExit(main())
