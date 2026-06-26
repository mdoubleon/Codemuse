"""End-to-end local memory index and retrieval pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.memory.indexer import WorkspaceIndexReport, build_workspace_file_index
from codemuse.memory.retrieval import RetrievalResult, format_retrieval_hits, retrieve_memory


@dataclass(frozen=True)
class MemoryPipelineReport:
    index: WorkspaceIndexReport
    retrieval_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index.to_dict(),
            "retrieval_ready": self.retrieval_ready,
        }


def refresh_memory_index(workspace: Path, *, max_files: int = 300) -> MemoryPipelineReport:
    """Build or refresh the local deterministic workspace index."""
    report = build_workspace_file_index(workspace, max_files=max_files)
    return MemoryPipelineReport(index=report, retrieval_ready=report.chunk_count > 0)


def search_memory_pipeline(workspace: Path, query: str, *, limit: int = 6) -> RetrievalResult:
    """Search existing memories and the latest local file index."""
    return retrieve_memory(workspace, query, limit=limit)


def format_memory_pipeline_search(result: RetrievalResult) -> str:
    return format_retrieval_hits(result.hits)
