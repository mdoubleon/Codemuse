"""Unified local retrieval across project memory, blueprint memory, and indexed files."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.memory.blueprint_memory import BlueprintStore
from codemuse.memory.file_memory_bm25 import rank_bm25
from codemuse.memory.file_memory_chunker import FileMemoryChunk, chunk_text
from codemuse.memory.file_memory_search import search_file_memory
from codemuse.memory.file_memory_store import FileMemoryStore
from codemuse.memory.file_memory_vector import FileMemoryVectorIndex
from codemuse.memory.reranker import rerank_chunks, summarize_hit_distribution


@dataclass(frozen=True)
class RetrievalHit:
    """A retrieved memory chunk with normalized scoring metadata."""

    source: str
    title: str
    content: str
    score: float
    path: str = ""
    start_line: int = 1
    end_line: int = 1
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    hits: list[RetrievalHit]
    distribution: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [hit.to_dict() for hit in self.hits],
            "distribution": self.distribution,
        }


def retrieve_memory(
    workspace: Path,
    query: str,
    *,
    limit: int = 6,
    include_indexed_files: bool = True,
) -> RetrievalResult:
    """Retrieve relevant memory from all local deterministic sources."""
    root = workspace.resolve()
    candidates: list[tuple[FileMemoryChunk, float, str]] = []
    chunks = _memory_chunks(root)
    candidates.extend((chunk, score, "memory_bm25") for chunk, score in rank_bm25(query, chunks, limit=limit * 3))

    if include_indexed_files:
        index_path = root / ".data" / "codemuse" / "rag" / "vector_index.json"
        vector_index = FileMemoryVectorIndex(index_path)
        vector_index.load()
        candidates.extend((chunk, score, "file_vector") for chunk, score in vector_index.search(query, limit=limit * 3))
        indexed_chunks = [record.chunk for record in vector_index.records]
        candidates.extend((chunk, score, "file_bm25") for chunk, score in rank_bm25(query, indexed_chunks, limit=limit * 3))

    ranked = rerank_chunks(query, candidates, limit=limit)
    hits = [_hit_from_chunk(chunk, score, details) for chunk, score, details in ranked]
    return RetrievalResult(query=query, hits=hits, distribution=summarize_hit_distribution(ranked))


def format_retrieval_hits(hits: list[RetrievalHit]) -> str:
    if not hits:
        return "No generic memory matched."
    lines: list[str] = []
    current_source = ""
    for hit in hits:
        label = _source_label(hit.source)
        if label != current_source:
            if lines:
                lines.append("")
            lines.append(f"# {label}")
            lines.append("")
            current_source = label
        location = f"{hit.path}:{hit.start_line}" if hit.path else hit.source
        lines.append(f"## {hit.title}")
        lines.append(f"- source: {hit.source}")
        lines.append(f"- score: {hit.score:.3f}")
        lines.append(f"- location: {location}")
        if hit.tags:
            lines.append("- tags: " + ", ".join(hit.tags))
        lines.append("")
        lines.append(hit.content)
        lines.append("")
    return "\n".join(lines).strip()


def _source_label(source: str) -> str:
    labels = {
        "project_memory": "Project Memory",
        "blueprint_memory": "Repository Blueprint Memory",
        "workspace_file": "Indexed Workspace Files",
        "indexed_file": "Indexed Workspace Files",
    }
    return labels.get(source, source.replace("_", " ").title())


def _memory_chunks(root: Path) -> list[FileMemoryChunk]:
    chunks: list[FileMemoryChunk] = []
    project_store = FileMemoryStore(root / ".data" / "codemuse" / "project_memory")
    for item in project_store.list():
        chunks.extend(
            chunk_text(
                item.content,
                path=f"project_memory/{item.memory_id}",
                title=item.title,
                tags=item.tags,
                metadata={
                    "source": "project_memory",
                    "memory_id": item.memory_id,
                    "category": item.category,
                    "source_paths": item.source_paths,
                },
            )
        )

    blueprint_store = BlueprintStore(root / ".data" / "codemuse" / "blueprint_memory")
    for item in blueprint_store.search_memory("", limit=500):
        chunks.extend(
            chunk_text(
                item.content,
                path=f"blueprint_memory/{item.memory_id}",
                title=item.title,
                tags=item.tags,
                metadata={
                    "source": "blueprint_memory",
                    "memory_id": item.memory_id,
                    "blueprint_id": item.blueprint_id,
                    "repo_id": item.repo_id,
                    "category": item.category,
                    "source_paths": item.source_paths,
                },
            )
        )
    return chunks


def _hit_from_chunk(chunk: FileMemoryChunk, score: float, details: dict[str, float | str]) -> RetrievalHit:
    source = str(chunk.metadata.get("source") or "indexed_file")
    return RetrievalHit(
        source=source,
        title=chunk.title or chunk.path,
        content=chunk.text,
        score=round(score, 6),
        path=chunk.path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        tags=chunk.tags,
        metadata={**chunk.metadata, "rerank": details},
    )
