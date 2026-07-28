"""预留终端交互界面的包入口。"""
"""Dependency-free interactive CodeMuse shell."""

from codemuse.tui.controller import TuiController
from codemuse.tui.main import tui_main

__all__ = ["TuiController", "tui_main"]
