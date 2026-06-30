"""Persistent deterministic vector index for workspace memory chunks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.memory.embedding import cosine_similarity, hashed_embedding
from codemuse.memory.file_memory_chunker import FileMemoryChunk


@dataclass(frozen=True)
class VectorRecord:
    """保存 Vector 记录的结构化数据。"""
    chunk: FileMemoryChunk
    embedding: list[float]

    def to_dict(self) -> dict[str, Any]:
        """将 VectorRecord 转换为可序列化字典。"""
        return {"chunk": self.chunk.to_dict(), "embedding": self.embedding}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VectorRecord":
        """从字典数据恢复 VectorRecord。"""
        return cls(
            chunk=FileMemoryChunk.from_dict(dict(payload["chunk"])),
            embedding=[float(item) for item in payload.get("embedding", [])],
        )


class FileMemoryVectorIndex:
    """JSON-backed vector index for deterministic local retrieval."""

    def __init__(self, path: Path) -> None:
        """初始化 FileMemoryVectorIndex 并保存运行依赖。"""
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records: list[VectorRecord] = []

    def build(self, chunks: list[FileMemoryChunk]) -> None:
        """构建记忆检索。"""
        self.records = [VectorRecord(chunk=chunk, embedding=hashed_embedding(_embed_text(chunk))) for chunk in chunks]

    def save(self) -> Path:
        """保存记忆检索。"""
        payload = {"records": [record.to_dict() for record in self.records]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def load(self) -> None:
        """加载记忆检索。"""
        if not self.path.exists():
            self.records = []
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.records = [VectorRecord.from_dict(item) for item in payload.get("records", [])]

    def search(self, query: str, *, limit: int = 10) -> list[tuple[FileMemoryChunk, float]]:
        """搜索记忆检索。"""
        if not self.records:
            self.load()
        query_embedding = hashed_embedding(query)
        scored = [
            (record.chunk, cosine_similarity(query_embedding, record.embedding))
            for record in self.records
        ]
        scored = [item for item in scored if item[1] > 0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


def _embed_text(chunk: FileMemoryChunk) -> str:
    """处理 嵌入文本。"""
    return " ".join([chunk.title, chunk.path, " ".join(chunk.tags), chunk.text])
