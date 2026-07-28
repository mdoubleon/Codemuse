"""Dependency-free terminal chat entry point."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from codemuse.tui.controller import TuiController


def tui_main(workspace: Path, session_id: str | None = None, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    controller = TuiController(workspace, session_id=session_id)
    output_stream.write(f"CodeMuse session {controller.session_id}\n")
    output_stream.flush()
    while not controller.should_exit:
        if input_stream is sys.stdin and input_stream.isatty():
            output_stream.write("codemuse> ")
            output_stream.flush()
        raw = input_stream.readline()
        if raw == "":
            break
        try:
            response = controller.submit(raw)
        except Exception as exc:  # noqa: BLE001 - interactive sessions continue after command errors
            response = f"error: {exc}"
        if response:
            output_stream.write(response + "\n")
            output_stream.flush()
    return 0
