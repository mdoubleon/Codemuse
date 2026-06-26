"""Script entrypoint for CodeMuse deterministic baseline evals."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.benchmarks.baseline import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli())
