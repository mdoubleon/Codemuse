"""持久化仓库蓝图和蓝图记忆，并提供关键词检索。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from codemuse.domain.blueprint import BlueprintMemoryItem, RepoBlueprint


class BlueprintStore:
    """BlueprintStore：封装该类数据的本地持久化读写。"""
    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.blueprints_dir = self.root / "blueprints"
        self.memories_dir = self.root / "memories"
        self.blueprints_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

    def save_blueprint(self, blueprint: RepoBlueprint) -> Path:
        """把 RepoBlueprint 写入本地蓝图 JSON 文件。"""
        path = self.blueprints_dir / f"{blueprint.blueprint_id}.json"
        path.write_text(json.dumps(blueprint.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_memory_items(self, items: list[BlueprintMemoryItem]) -> list[Path]:
        """把蓝图拆分后的记忆条目逐条写入本地 JSON 文件。"""
        paths: list[Path] = []
        for item in items:
            path = self.memories_dir / f"{item.memory_id}.json"
            path.write_text(json.dumps(item.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            paths.append(path)
        return paths

    def list_blueprints(self) -> list[RepoBlueprint]:
        """读取并按时间倒序返回已保存的仓库蓝图。"""
        blueprints: list[RepoBlueprint] = []
        for path in sorted(self.blueprints_dir.glob("*.json")):
            try:
                blueprints.append(RepoBlueprint.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return sorted(blueprints, key=lambda item: item.created_at, reverse=True)

    def search_memory(self, query: str, *, limit: int = 5) -> list[BlueprintMemoryItem]:
        """在已保存的蓝图记忆中按关键词打分并返回最相关结果。"""
        items = self._load_memory_items()
        if not query.strip():
            return sorted(items, key=lambda item: item.created_at, reverse=True)[:limit]
        query_terms = _terms(query)
        scored = [(_score(item, query_terms), item) for item in items]
        matches = [(score, item) for score, item in scored if score > 0]
        matches.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return [item for _, item in matches[:limit]]

    def _load_memory_items(self) -> list[BlueprintMemoryItem]:
        """加载本地保存的所有蓝图记忆条目。"""
        items: list[BlueprintMemoryItem] = []
        for path in sorted(self.memories_dir.glob("*.json")):
            try:
                items.append(BlueprintMemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return items


def format_memory_search_results(items: list[BlueprintMemoryItem]) -> str:
    """把蓝图记忆命中结果整理成模型和用户可读文本。"""
    if not items:
        return "No blueprint memory matched."
    lines: list[str] = []
    for item in items:
        tags = ", ".join(item.tags)
        lines.append(f"## {item.title}")
        lines.append(f"- category: {item.category}")
        lines.append(f"- repo_id: {item.repo_id}")
        if tags:
            lines.append(f"- tags: {tags}")
        if item.source_paths:
            lines.append("- source_paths: " + ", ".join(item.source_paths[:8]))
        lines.append("")
        lines.append(item.content)
        lines.append("")
    return "\n".join(lines).strip()


def _score(item: BlueprintMemoryItem, query_terms: list[str]) -> int:
    """按查询词在蓝图记忆中的命中情况计算排序分数。"""
    haystack = " ".join(
        [
            item.title,
            item.content,
            item.category,
            item.repo_id,
            " ".join(item.tags),
            " ".join(item.source_paths),
        ]
    ).lower()
    score = 0
    for term in query_terms:
        if term in haystack:
            score += 2
        score += haystack.count(term)
    return score


def _terms(query: str) -> list[str]:
    """将查询文本拆成用于匹配的关键词。"""
    return [term for term in re.split(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", query.lower()) if term]
