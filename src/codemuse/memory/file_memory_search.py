"""实现 memory/file_memory_search.py 对应的业务边界和辅助逻辑。"""
from __future__ import annotations

import re

from codemuse.memory.file_memory_store import FileMemoryStore
from codemuse.memory.types import MemoryItem


def search_file_memory(store: FileMemoryStore, query: str, *, limit: int = 5) -> list[MemoryItem]:
    """在通用项目记忆中按关键词匹配并排序。"""
    items = store.list()
    if not query.strip():
        return items[:limit]
    terms = _terms(query)
    scored = [(_score(item, terms), item) for item in items]
    matches = [(score, item) for score, item in scored if score > 0]
    matches.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
    return [item for _, item in matches[:limit]]


def _score(item: MemoryItem, terms: list[str]) -> int:
    """计算搜索或排序时使用的简单相关性分数。"""
    haystack = " ".join(
        [
            item.title,
            item.content,
            item.category,
            item.source,
            " ".join(item.tags),
            " ".join(item.source_paths),
        ]
    ).lower()
    score = 0
    for term in terms:
        if term in haystack:
            score += 2
        score += haystack.count(term)
    return score


def _terms(query: str) -> list[str]:
    """将查询文本拆成用于匹配的关键词。"""
    return [term for term in re.split(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", query.lower()) if term]
