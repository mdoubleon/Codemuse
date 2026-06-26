"""用 JSON 文件保存通用项目记忆，支持新增和列出。"""
from __future__ import annotations

import json
from pathlib import Path

from codemuse.memory.types import MemoryItem


class FileMemoryStore:
    """JSON 文件版通用记忆存储。

    当前阶段先用文件存储，方便学习和调试；以后可以替换成 SQLite/vector store。
    """

    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.items_dir = self.root / "items"
        self.items_dir.mkdir(parents=True, exist_ok=True)

    def save(self, item: MemoryItem) -> Path:
        """将对象写入本地存储。"""
        path = self.items_dir / f"{item.memory_id}.json"
        path.write_text(json.dumps(item.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def add(
        self,
        *,
        title: str,
        content: str,
        category: str = "note",
        tags: list[str] | None = None,
        source: str = "manual",
        source_paths: list[str] | None = None,
    ) -> MemoryItem:
        """根据标题、内容和标签创建一条新项目记忆并保存。"""
        item = MemoryItem.create(
            title=title,
            content=content,
            category=category,
            tags=tags or [],
            source=source,
            source_paths=source_paths or [],
        )
        self.save(item)
        return item

    def list(self) -> list[MemoryItem]:
        """列出当前存储或目录中的对象。"""
        items: list[MemoryItem] = []
        for path in sorted(self.items_dir.glob("*.json")):
            try:
                items.append(MemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return sorted(items, key=lambda item: item.created_at, reverse=True)
