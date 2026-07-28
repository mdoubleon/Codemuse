"""Layered Markdown prompt loading for CodeMuse."""
from __future__ import annotations

from pathlib import Path


BUILTIN_PROMPTS_DIR = Path(__file__).resolve().parent


def prompt_search_paths(workspace: Path, extra_paths: list[Path] | None = None) -> list[Path]:
    """Return prompt roots in descending precedence order."""
    workspace = workspace.resolve()
    paths = [workspace / ".codemuse" / "prompts", workspace / "prompts", BUILTIN_PROMPTS_DIR]
    for path in extra_paths or []:
        candidate = _safe_resolve(path)
        if candidate not in paths:
            paths.append(candidate)
    return paths


def load_prompt_templates(workspace: Path, extra_paths: list[Path] | None = None) -> dict[str, str]:
    """Load all Markdown templates, allowing higher-priority roots to override."""
    templates: dict[str, str] = {}
    for root in reversed(prompt_search_paths(workspace, extra_paths=extra_paths)):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            templates[path.stem] = path.read_text(encoding="utf-8")
    return templates


def load_prompt(name: str, workspace: Path, extra_paths: list[Path] | None = None) -> str:
    """Load one named template without allowing path traversal."""
    clean = name.strip()
    if not clean or Path(clean).name != clean or clean in {".", ".."}:
        raise ValueError("Prompt name must be a plain file name.")
    stem = clean[:-3] if clean.lower().endswith(".md") else clean
    templates = load_prompt_templates(workspace, extra_paths=extra_paths)
    try:
        return templates[stem]
    except KeyError as exc:
        raise FileNotFoundError(f"Prompt template not found: {stem}") from exc


def _safe_resolve(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        return candidate.resolve()
    except (OSError, PermissionError):
        return candidate.absolute()
