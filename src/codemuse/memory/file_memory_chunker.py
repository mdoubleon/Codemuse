"""Workspace file chunking for local memory indexing."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_INCLUDE_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".html",
}
DEFAULT_IGNORED_DIRS = {
    ".git",
    ".data",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
}


@dataclass(frozen=True)
class FileMemoryChunk:
    """A bounded text chunk from a workspace file."""

    chunk_id: str
    path: str
    text: str
    start_line: int
    end_line: int
    title: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """将 FileMemoryChunk 转换为可序列化字典。"""
        return {
            "chunk_id": self.chunk_id,
            "path": self.path,
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "title": self.title,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FileMemoryChunk":
        """从字典数据恢复 FileMemoryChunk。"""
        return cls(
            chunk_id=str(payload["chunk_id"]),
            path=str(payload.get("path") or ""),
            text=str(payload.get("text") or ""),
            start_line=int(payload.get("start_line") or 1),
            end_line=int(payload.get("end_line") or 1),
            title=str(payload.get("title") or ""),
            tags=[str(item) for item in payload.get("tags", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


def chunk_text(
    text: str,
    *,
    path: str,
    max_chars: int = 1200,
    overlap_lines: int = 4,
    title: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[FileMemoryChunk]:
    """Split text into stable line-aware chunks."""
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[FileMemoryChunk] = []
    index = 0
    while index < len(lines):
        current: list[str] = []
        start = index
        size = 0
        while index < len(lines) and (not current or size + len(lines[index]) + 1 <= max_chars):
            current.append(lines[index])
            size += len(lines[index]) + 1
            index += 1
        end = max(start, index - 1)
        chunk_text_value = "\n".join(current).strip()
        if chunk_text_value:
            chunks.append(
                FileMemoryChunk(
                    chunk_id=_chunk_id(path, start + 1, end + 1, chunk_text_value),
                    path=path,
                    text=chunk_text_value,
                    start_line=start + 1,
                    end_line=end + 1,
                    title=title or path,
                    tags=list(tags or []),
                    metadata=dict(metadata or {}),
                )
            )
        if index >= len(lines):
            break
        index = max(index - overlap_lines, start + 1)
    return chunks


def chunk_workspace(
    workspace: Path,
    *,
    max_files: int = 300,
    max_file_bytes: int = 250_000,
    max_chars: int = 1200,
    suffixes: set[str] | None = None,
) -> list[FileMemoryChunk]:
    """Create chunks for readable project files under a workspace."""
    root = workspace.resolve()
    chunks: list[FileMemoryChunk] = []
    for path in _iter_indexable_files(root, suffixes=suffixes or DEFAULT_INCLUDE_SUFFIXES):
        if len(chunks) >= max_files * 4:
            break
        try:
            if path.stat().st_size > max_file_bytes:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        chunks.extend(
            chunk_text(
                text,
                path=relative,
                max_chars=max_chars,
                title=path.name,
                tags=[path.suffix.lstrip(".") or "text"],
                metadata={"source": "workspace_file"},
            )
        )
        if len({chunk.path for chunk in chunks}) >= max_files:
            break
    return chunks


def _iter_indexable_files(root: Path, *, suffixes: set[str]) -> list[Path]:
    """遍历indexable文件。"""
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in DEFAULT_IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in suffixes:
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def _chunk_id(path: str, start_line: int, end_line: int, text: str) -> str:
    """处理 分块ID。"""
    digest = hashlib.sha256(f"{path}:{start_line}:{end_line}:{text}".encode("utf-8")).hexdigest()
    return digest[:24]
