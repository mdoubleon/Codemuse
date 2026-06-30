"""把项目记忆保存和混合检索能力注册为 Agent 工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.memory.file_memory_store import FileMemoryStore
from codemuse.memory.index_pipeline import format_memory_pipeline_search, refresh_memory_index, search_memory_pipeline
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class SaveProjectMemoryTool(BaseTool):
    """保存可在后续轮次复用的项目或学习记忆。"""

    @property
    def spec(self) -> ToolSpec:
        """返回保存项目记忆工具的 ToolSpec 声明。"""
        return ToolSpec(
            name="save_project_memory",
            description="Save a reusable project or learning memory note for future turns.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source_paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "content"],
            },
            permission_domain="write",
            requires_confirmation=False,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """把模型传入的记忆内容写入本地项目记忆存储。"""
        store = FileMemoryStore(self.workspace / ".data" / "codemuse" / "project_memory")
        item = store.add(
            title=str(arguments.get("title") or "Untitled memory"),
            content=str(arguments.get("content") or ""),
            category=str(arguments.get("category") or "note"),
            tags=[str(item) for item in arguments.get("tags", [])],
            source="tool",
            source_paths=[str(item) for item in arguments.get("source_paths", [])],
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=(
                "Saved project memory.\n\n"
                f"- memory_id: {item.memory_id}\n"
                f"- title: {item.title}\n"
                f"- category: {item.category}"
            ),
            details={"memory": item.to_dict()},
        )


class SearchProjectMemoryTool(BaseTool):
    """检索项目记忆、蓝图记忆和已索引的 workspace 文件。"""

    @property
    def spec(self) -> ToolSpec:
        """返回搜索项目记忆工具的 ToolSpec 声明。"""
        return ToolSpec(
            name="search_project_memory",
            description="Search saved project memory, blueprint memory, and indexed workspace files.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "refresh_index": {"type": "boolean"},
                },
                "required": ["query"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """按查询词执行混合记忆检索并返回格式化结果。"""
        query = str(arguments.get("query") or "")
        limit = int(arguments.get("limit") or 5)
        index_report = refresh_memory_index(self.workspace) if bool(arguments.get("refresh_index")) else None
        result = search_memory_pipeline(self.workspace, query, limit=limit)
        return ToolResult(
            tool_name=self.spec.name,
            content=format_memory_pipeline_search(result),
            details={
                "matches": [hit.to_dict() for hit in result.hits],
                "distribution": result.distribution,
                "index_report": index_report.to_dict() if index_report else None,
            },
        )


def register_file_memory_tools(registry, workspace: Path) -> None:
    """把项目记忆保存和搜索工具注册到 ToolRegistry。"""
    registry.register(SaveProjectMemoryTool(workspace))
    registry.register(SearchProjectMemoryTool(workspace))
