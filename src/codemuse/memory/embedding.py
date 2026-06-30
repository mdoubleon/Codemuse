"""Deterministic local embeddings for offline memory retrieval."""
from __future__ import annotations

import hashlib
import math
import re


def tokenize(text: str) -> list[str]:
    """Split English, code-ish identifiers, and CJK text into stable search terms."""
    terms = re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]+", text.lower())
    expanded: list[str] = []
    for term in terms:
        expanded.append(term)
        for part in re.split(r"[_\-]+", term):
            if part and part != term:
                expanded.append(part)
    return expanded


def hashed_embedding(text: str, *, dimensions: int = 96) -> list[float]:
    """Create a deterministic normalized feature vector without network calls."""
    vector = [0.0 for _ in range(dimensions)]
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + min(len(token), 16) / 16.0
        vector[index] += sign * weight
    return normalize(vector)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """处理 cosinesimilarity。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def normalize(vector: list[float]) -> list[float]:
    """处理 normalize。"""
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return vector
    return [value / length for value in vector]
