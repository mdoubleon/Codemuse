"""Hybrid reranking for local memory retrieval."""
from __future__ import annotations

from collections import defaultdict

from codemuse.memory.embedding import tokenize
from codemuse.memory.file_memory_bm25 import lexical_overlap_score
from codemuse.memory.file_memory_chunker import FileMemoryChunk


def rerank_chunks(
    query: str,
    candidates: list[tuple[FileMemoryChunk, float, str]],
    *,
    limit: int = 8,
) -> list[tuple[FileMemoryChunk, float, dict[str, float | str]]]:
    """Merge duplicate chunks and rank by vector, lexical, and path-title signals."""
    merged: dict[str, tuple[FileMemoryChunk, float, set[str]]] = {}
    for chunk, score, source in candidates:
        existing = merged.get(chunk.chunk_id)
        if existing is None:
            merged[chunk.chunk_id] = (chunk, score, {source})
        else:
            old_chunk, old_score, sources = existing
            sources.add(source)
            merged[chunk.chunk_id] = (old_chunk, max(old_score, score), sources)

    query_terms = set(tokenize(query))
    scored: list[tuple[FileMemoryChunk, float, dict[str, float | str]]] = []
    for chunk, base_score, sources in merged.values():
        lexical = lexical_overlap_score(query, chunk.text)
        path_bonus = _path_bonus(query_terms, chunk)
        source_bonus = 0.08 * len(sources)
        final_score = base_score + lexical * 1.25 + path_bonus + source_bonus
        scored.append(
            (
                chunk,
                final_score,
                {
                    "base_score": round(base_score, 6),
                    "lexical_overlap": round(lexical, 6),
                    "path_bonus": round(path_bonus, 6),
                    "source_bonus": round(source_bonus, 6),
                    "sources": ",".join(sorted(sources)),
                },
            )
        )
    scored.sort(key=lambda item: (item[1], item[0].path, -item[0].start_line), reverse=True)
    return scored[:limit]


def summarize_hit_distribution(hits: list[tuple[FileMemoryChunk, float, dict[str, float | str]]]) -> dict[str, int]:
    """汇总命中分布。"""
    distribution: dict[str, int] = defaultdict(int)
    for chunk, _score, _details in hits:
        distribution[chunk.metadata.get("source", "unknown")] += 1
    return dict(sorted(distribution.items()))


def _path_bonus(query_terms: set[str], chunk: FileMemoryChunk) -> float:
    """处理 path加分。"""
    if not query_terms:
        return 0.0
    haystack = " ".join([chunk.path, chunk.title, " ".join(chunk.tags)]).lower()
    matched = sum(1 for term in query_terms if term in haystack)
    return min(0.35, matched * 0.07)
