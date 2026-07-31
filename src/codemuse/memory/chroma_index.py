"""Optional persistent Chroma backend for long-term workspace memory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from codemuse.memory.embedding import hashed_embedding
from codemuse.memory.file_memory_chunker import FileMemoryChunk


class ChromaUnavailable(RuntimeError):
    pass


class ChromaMemoryIndex:
    """Store deterministic embeddings in Chroma without downloading an embedding model."""

    def __init__(
        self,
        path: Path,
        *,
        collection_name: str = "codemuse_workspace",
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.path = path.resolve()
        self.collection_name = collection_name
        self._client_factory = client_factory

    def build(self, chunks: list[FileMemoryChunk]) -> None:
        collection = self._collection()
        try:
            existing = collection.get(include=[])
        except TypeError:
            # Older Chroma releases do not accept an empty include list.
            existing = collection.get()
        existing_ids = [str(item) for item in existing.get("ids", [])]
        if existing_ids:
            collection.delete(ids=existing_ids)
        if not chunks:
            return
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=[hashed_embedding(_embed_text(chunk)) for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[{"chunk": json.dumps(chunk.to_dict(), ensure_ascii=False)} for chunk in chunks],
        )

    def search(self, query: str, *, limit: int = 10) -> list[tuple[FileMemoryChunk, float]]:
        if not query.strip() or limit < 1:
            return []
        collection = self._collection()
        count = int(collection.count())
        if count < 1:
            return []
        result = collection.query(
            query_embeddings=[hashed_embedding(query)],
            n_results=min(limit, count),
            include=["metadatas", "distances"],
        )
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[tuple[FileMemoryChunk, float]] = []
        for metadata, distance in zip(metadatas, distances):
            if not isinstance(metadata, dict) or not metadata.get("chunk"):
                continue
            chunk = FileMemoryChunk.from_dict(json.loads(str(metadata["chunk"])))
            score = max(0.0, 1.0 - float(distance))
            hits.append((chunk, score))
        return hits

    def count(self) -> int:
        return int(self._collection().count())

    def _collection(self):
        if self._client_factory is not None:
            self.path.mkdir(parents=True, exist_ok=True)
            client = self._client_factory(str(self.path))
        else:
            try:
                import chromadb
            except ImportError as exc:
                raise ChromaUnavailable("Install codemuse[chroma] to enable the Chroma memory backend") from exc
            self.path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.path))
        return client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine", "codemuse:embedding": "hashed-96"},
        )


def _embed_text(chunk: FileMemoryChunk) -> str:
    return " ".join([chunk.title, chunk.path, " ".join(chunk.tags), chunk.text])


__all__ = ["ChromaMemoryIndex", "ChromaUnavailable"]
