"""模块说明：CodeMuse 脚本入口，用于启动 CLI 或 HTTP 服务。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.cli.main import main


if __name__ == "__main__":
    # 脚本只负责设置源码路径和默认 workspace；真正的 CLI 解析在 codemuse.cli.main。
    raise SystemExit(main(default_workspace=ROOT))
