"""Workspace indexing helpers for local RAG."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.memory.file_memory_chunker import FileMemoryChunk, chunk_workspace
from codemuse.memory.file_memory_vector import FileMemoryVectorIndex


@dataclass(frozen=True)
class WorkspaceIndexReport:
    """保存 WorkspaceIndex 报告的结构化数据。"""
    workspace: str
    index_path: str
    file_count: int
    chunk_count: int

    def to_dict(self) -> dict[str, Any]:
        """将 WorkspaceIndexReport 转换为可序列化字典。"""
        return {
            "workspace": self.workspace,
            "index_path": self.index_path,
            "file_count": self.file_count,
            "chunk_count": self.chunk_count,
        }


def build_workspace_file_index(
    workspace: Path,
    *,
    max_files: int = 300,
    max_file_bytes: int = 250_000,
    max_chars: int = 1200,
) -> WorkspaceIndexReport:
    """Scan readable workspace files and save a deterministic vector index."""
    root = workspace.resolve()
    chunks = chunk_workspace(
        root,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_chars=max_chars,
    )
    index_path = root / ".data" / "codemuse" / "rag" / "vector_index.json"
    index = FileMemoryVectorIndex(index_path)
    index.build(chunks)
    index.save()
    return WorkspaceIndexReport(
        workspace=str(root),
        index_path=str(index_path),
        file_count=len({chunk.path for chunk in chunks}),
        chunk_count=len(chunks),
    )


def load_indexed_chunks(workspace: Path) -> list[FileMemoryChunk]:
    """加载indexed分块。"""
    index = FileMemoryVectorIndex(workspace.resolve() / ".data" / "codemuse" / "rag" / "vector_index.json")
    index.load()
    return [record.chunk for record in index.records]
