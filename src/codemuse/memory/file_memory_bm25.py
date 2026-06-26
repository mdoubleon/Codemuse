"""Small BM25-style lexical ranking for local memory chunks."""
from __future__ import annotations

import math
from collections import Counter

from codemuse.memory.embedding import tokenize
from codemuse.memory.file_memory_chunker import FileMemoryChunk


def rank_bm25(
    query: str,
    chunks: list[FileMemoryChunk],
    *,
    limit: int = 10,
    k1: float = 1.4,
    b: float = 0.75,
) -> list[tuple[FileMemoryChunk, float]]:
    """Return chunks ranked by BM25-like lexical relevance."""
    query_terms = tokenize(query)
    if not query_terms or not chunks:
        return []
    documents = [tokenize(_chunk_haystack(chunk)) for chunk in chunks]
    avgdl = sum(len(doc) for doc in documents) / max(len(documents), 1)
    document_frequency: Counter[str] = Counter()
    for doc in documents:
        document_frequency.update(set(doc))
    scored: list[tuple[FileMemoryChunk, float]] = []
    total_docs = len(documents)
    for chunk, doc in zip(chunks, documents):
        counts = Counter(doc)
        score = 0.0
        for term in query_terms:
            if counts[term] == 0:
                continue
            idf = math.log(1 + (total_docs - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = counts[term] + k1 * (1 - b + b * len(doc) / max(avgdl, 1.0))
            score += idf * (counts[term] * (k1 + 1)) / denominator
        if score > 0:
            scored.append((chunk, score))
    scored.sort(key=lambda pair: (pair[1], pair[0].path, -pair[0].start_line), reverse=True)
    return scored[:limit]


def lexical_overlap_score(query: str, text: str) -> float:
    """A compact overlap score used by the reranker."""
    query_terms = set(tokenize(query))
    if not query_terms:
        return 0.0
    text_terms = set(tokenize(text))
    return len(query_terms & text_terms) / len(query_terms)


def _chunk_haystack(chunk: FileMemoryChunk) -> str:
    return " ".join([chunk.title, chunk.path, " ".join(chunk.tags), chunk.text])
