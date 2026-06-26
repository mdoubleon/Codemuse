"""定义仓库索引、架构蓝图和蓝图记忆的数据模型。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RepoIndex:
    """仓库静态索引结果，记录文件规模、语言分布和关键文件线索。"""
    repo_id: str
    root_path: str
    file_count: int
    total_size: int
    languages: dict[str, int] = field(default_factory=dict)
    important_files: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    package_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    route_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    agent_related_files: list[str] = field(default_factory=list)
    tree_summary: str = ""
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """把 RepoIndex 转成可写入文件或 API 响应的字典。"""
        return {
            "repo_id": self.repo_id,
            "root_path": self.root_path,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "languages": self.languages,
            "important_files": self.important_files,
            "entrypoints": self.entrypoints,
            "package_files": self.package_files,
            "config_files": self.config_files,
            "route_files": self.route_files,
            "test_files": self.test_files,
            "agent_related_files": self.agent_related_files,
            "tree_summary": self.tree_summary,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoIndex":
        """把字典里的字段校正并恢复成 RepoIndex 对象。"""
        return cls(
            repo_id=str(data["repo_id"]),
            root_path=str(data["root_path"]),
            file_count=int(data["file_count"]),
            total_size=int(data["total_size"]),
            languages=dict(data.get("languages") or {}),
            important_files=list(data.get("important_files") or []),
            entrypoints=list(data.get("entrypoints") or []),
            package_files=list(data.get("package_files") or []),
            config_files=list(data.get("config_files") or []),
            route_files=list(data.get("route_files") or []),
            test_files=list(data.get("test_files") or []),
            agent_related_files=list(data.get("agent_related_files") or []),
            tree_summary=str(data.get("tree_summary") or ""),
            truncated=bool(data.get("truncated") or False),
        )


@dataclass
class ModuleSummary:
    """仓库蓝图中的单个模块摘要。"""
    path: str
    role: str
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """把 ModuleSummary 转成可写入文件或 API 响应的字典。"""
        return {"path": self.path, "role": self.role, "signals": self.signals}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleSummary":
        """把字典里的字段校正并恢复成 ModuleSummary 对象。"""
        return cls(
            path=str(data["path"]),
            role=str(data["role"]),
            signals=list(data.get("signals") or []),
        )


@dataclass
class RepoBlueprint:
    """从仓库索引中提炼出的架构蓝图和可复用经验。"""
    blueprint_id: str
    repo_id: str
    source_root: str
    title: str
    problem_statement: str
    tech_stack: list[str] = field(default_factory=list)
    minimal_architecture: list[str] = field(default_factory=list)
    modules: list[ModuleSummary] = field(default_factory=list)
    data_flow: list[str] = field(default_factory=list)
    reusable_patterns: list[str] = field(default_factory=list)
    learning_notes: list[str] = field(default_factory=list)
    key_files: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """把 RepoBlueprint 转成可写入文件或 API 响应的字典。"""
        return {
            "blueprint_id": self.blueprint_id,
            "repo_id": self.repo_id,
            "source_root": self.source_root,
            "title": self.title,
            "problem_statement": self.problem_statement,
            "tech_stack": self.tech_stack,
            "minimal_architecture": self.minimal_architecture,
            "modules": [module.to_dict() for module in self.modules],
            "data_flow": self.data_flow,
            "reusable_patterns": self.reusable_patterns,
            "learning_notes": self.learning_notes,
            "key_files": self.key_files,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoBlueprint":
        """把字典里的字段校正并恢复成 RepoBlueprint 对象。"""
        return cls(
            blueprint_id=str(data["blueprint_id"]),
            repo_id=str(data["repo_id"]),
            source_root=str(data["source_root"]),
            title=str(data["title"]),
            problem_statement=str(data.get("problem_statement") or ""),
            tech_stack=list(data.get("tech_stack") or []),
            minimal_architecture=list(data.get("minimal_architecture") or []),
            modules=[ModuleSummary.from_dict(item) for item in data.get("modules", [])],
            data_flow=list(data.get("data_flow") or []),
            reusable_patterns=list(data.get("reusable_patterns") or []),
            learning_notes=list(data.get("learning_notes") or []),
            key_files=list(data.get("key_files") or []),
            created_at=float(data.get("created_at") or time.time()),
        )


@dataclass
class BlueprintMemoryItem:
    """可检索的蓝图记忆片段，用于后续项目设计和代码任务召回。"""
    memory_id: str
    blueprint_id: str
    repo_id: str
    category: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """把 BlueprintMemoryItem 转成可写入文件或 API 响应的字典。"""
        return {
            "memory_id": self.memory_id,
            "blueprint_id": self.blueprint_id,
            "repo_id": self.repo_id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "source_paths": self.source_paths,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlueprintMemoryItem":
        """把字典里的字段校正并恢复成 BlueprintMemoryItem 对象。"""
        return cls(
            memory_id=str(data["memory_id"]),
            blueprint_id=str(data["blueprint_id"]),
            repo_id=str(data["repo_id"]),
            category=str(data["category"]),
            title=str(data["title"]),
            content=str(data.get("content") or ""),
            tags=list(data.get("tags") or []),
            source_paths=list(data.get("source_paths") or []),
            created_at=float(data.get("created_at") or time.time()),
        )
