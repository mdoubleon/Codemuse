from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.memory.chroma_index import ChromaMemoryIndex
from codemuse.memory.file_memory_chunker import FileMemoryChunk


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, include=None):
        return {"ids": list(self.rows)}

    def delete(self, *, ids):
        for item in ids:
            self.rows.pop(item, None)

    def upsert(self, *, ids, embeddings, documents, metadatas):
        for item_id, embedding, document, metadata in zip(ids, embeddings, documents, metadatas):
            self.rows[item_id] = {"embedding": embedding, "document": document, "metadata": metadata}

    def query(self, *, query_embeddings, n_results, include):
        rows = list(self.rows.values())[:n_results]
        return {
            "metadatas": [[item["metadata"] for item in rows]],
            "distances": [[0.1 for _item in rows]],
        }

    def count(self):
        return len(self.rows)


class _FakeClient:
    def __init__(self, collection: _FakeCollection) -> None:
        self.collection = collection

    def get_or_create_collection(self, **_kwargs):
        return self.collection


class ChromaMemoryTests(unittest.TestCase):
    def test_chroma_adapter_round_trips_chunks_with_explicit_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            collection = _FakeCollection()
            index = ChromaMemoryIndex(
                Path(raw),
                client_factory=lambda _path: _FakeClient(collection),
            )
            chunk = FileMemoryChunk("chunk-1", "README.md", "Agent runtime tools", 1, 1)

            index.build([chunk])
            hits = index.search("runtime", limit=3)

            self.assertEqual(1, index.count())
            self.assertEqual("chunk-1", hits[0][0].chunk_id)
            self.assertGreater(hits[0][1], 0)
            self.assertEqual(96, len(collection.rows["chunk-1"]["embedding"]))


if __name__ == "__main__":
    unittest.main()
