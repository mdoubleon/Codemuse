"""定义记忆检索和索引流程中共享的数据类型。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryItem:
    """一条通用项目记忆。

    blueprint memory 记的是“仓库架构总结”；MemoryItem 记的是更通用的学习内容、
    项目约定、模块理解、调试结论等。
    """

    memory_id: str
    title: str
    content: str
    category: str = "note"
    tags: list[str] = field(default_factory=list)
    source: str = "manual"
    source_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        content: str,
        category: str = "note",
        tags: list[str] | None = None,
        source: str = "manual",
        source_paths: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "MemoryItem":
        """创建一条新的领域记录或运行结果。"""
        return cls(
            memory_id=str(uuid.uuid4()),
            title=title,
            content=content,
            category=category,
            tags=tags or [],
            source=source,
            source_paths=source_paths or [],
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """把 MemoryItem 转成可写入文件或 API 响应的字典。"""
        return {
            "memory_id": self.memory_id,
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "source_paths": self.source_paths,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryItem":
        """把字典里的字段校正并恢复成 MemoryItem 对象。"""
        return cls(
            memory_id=str(payload["memory_id"]),
            title=str(payload.get("title") or ""),
            content=str(payload.get("content") or ""),
            category=str(payload.get("category") or "note"),
            tags=[str(item) for item in payload.get("tags", [])],
            source=str(payload.get("source") or "manual"),
            source_paths=[str(item) for item in payload.get("source_paths", [])],
            metadata=dict(payload.get("metadata") or {}),
            created_at=float(payload.get("created_at") or time.time()),
        )
