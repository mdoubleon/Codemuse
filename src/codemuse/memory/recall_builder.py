"""把记忆检索命中整理成可注入模型上下文的召回片段。"""
from __future__ import annotations

from codemuse.memory.types import MemoryItem


def build_memory_recall_text(items: list[MemoryItem]) -> str:
    """把通用记忆整理成模型可读文本。

    Store/Search 负责找记忆；RecallBuilder 负责把记忆变成 prompt 片段。
    """

    if not items:
        return "No generic memory matched."
    lines: list[str] = []
    for item in items:
        tags = ", ".join(item.tags)
        lines.append(f"## {item.title}")
        lines.append(f"- category: {item.category}")
        lines.append(f"- source: {item.source}")
        if tags:
            lines.append(f"- tags: {tags}")
        if item.source_paths:
            lines.append("- source_paths: " + ", ".join(item.source_paths[:8]))
        lines.append("")
        lines.append(item.content)
        lines.append("")
    return "\n".join(lines).strip()
