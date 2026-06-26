"""把仓库索引、架构分析和蓝图记忆暴露为 Agent 可调用工具。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.memory.blueprint_memory import BlueprintStore, format_memory_search_results
from codemuse.tools.project_plan import build_project_plan_from_blueprint, format_project_plan
from codemuse.tools.repo_analysis import blueprint_to_memory_items, build_repo_blueprint, format_blueprint_report
from codemuse.tools.repo_git import format_git_snapshot, format_import_record, import_repository, inspect_git_status, list_repo_cache
from codemuse.tools.repo_import import build_repo_import_plan, format_repo_import_plan
from codemuse.tools.repo_index import format_repo_index, index_local_repo
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class IndexRepoStructureTool(BaseTool):
    """IndexRepoStructureTool：扫描仓库结构并生成 RepoIndex 的工具。"""

        
    @property
    def spec(self) -> ToolSpec:
        """声明 IndexRepoStructureTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="index_repo_structure",
            description="Analyze a local repository structure and return tech-stack and architecture clues.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_files": {"type": "integer"},
                    "max_depth": {"type": "integer"},
                },
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 IndexRepoStructureTool 的具体动作，并返回 ToolResult。"""
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        index = index_local_repo(
            root,
            max_files=int(arguments.get("max_files") or 1200),
            max_depth=int(arguments.get("max_depth") or 4),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=format_repo_index(index),
            details={"repo_index": index.to_dict()},
        )


class AnalyzeRepoBlueprintTool(BaseTool):
    """AnalyzeRepoBlueprintTool：把仓库总结成最小架构蓝图的工具。"""

        
    @property
    def spec(self) -> ToolSpec:
        """声明 AnalyzeRepoBlueprintTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="analyze_repo_blueprint",
            description="Summarize a local repository into a minimal reusable architecture blueprint.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_files": {"type": "integer"},
                    "max_depth": {"type": "integer"},
                },
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 AnalyzeRepoBlueprintTool 的具体动作，并返回 ToolResult。"""
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        blueprint = build_repo_blueprint(
            root,
            max_files=int(arguments.get("max_files") or 1200),
            max_depth=int(arguments.get("max_depth") or 4),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=format_blueprint_report(blueprint),
            details={"blueprint": blueprint.to_dict()},
        )


class SaveBlueprintMemoryTool(BaseTool):
    """SaveBlueprintMemoryTool：分析仓库并保存蓝图记忆的工具。"""

        
    @property
    def spec(self) -> ToolSpec:
        """声明 SaveBlueprintMemoryTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="save_blueprint_memory",
            description="Analyze a local repository, save its blueprint, and split it into searchable learning memory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_files": {"type": "integer"},
                    "max_depth": {"type": "integer"},
                },
            },
            permission_domain="write",
            requires_confirmation=False,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 SaveBlueprintMemoryTool 的具体动作，并返回 ToolResult。"""
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        blueprint = build_repo_blueprint(
            root,
            max_files=int(arguments.get("max_files") or 1200),
            max_depth=int(arguments.get("max_depth") or 4),
        )
        store = BlueprintStore(self.workspace / ".data" / "codemuse" / "blueprint_memory")
        blueprint_path = store.save_blueprint(blueprint)
        memory_items = blueprint_to_memory_items(blueprint)
        memory_paths = store.save_memory_items(memory_items)
        content = "\n".join(
            [
                format_blueprint_report(blueprint),
                "",
                "## Saved Memory",
                f"- blueprint_file: {blueprint_path.relative_to(self.workspace).as_posix()}",
                f"- memory_items: {len(memory_paths)}",
            ]
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=content,
            details={
                "blueprint": blueprint.to_dict(),
                "blueprint_file": str(blueprint_path),
                "memory_files": [str(path) for path in memory_paths],
            },
        )


class SearchBlueprintMemoryTool(BaseTool):
    """SearchBlueprintMemoryTool：检索已经保存的蓝图记忆的工具。"""

        
    @property
    def spec(self) -> ToolSpec:
        """声明 SearchBlueprintMemoryTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="search_blueprint_memory",
            description="Search saved repository blueprint memory by keyword.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 SearchBlueprintMemoryTool 的具体动作，并返回 ToolResult。"""
        query = str(arguments.get("query") or "")
        limit = int(arguments.get("limit") or 5)
        store = BlueprintStore(self.workspace / ".data" / "codemuse" / "blueprint_memory")
        items = store.search_memory(query, limit=limit)
        return ToolResult(
            tool_name=self.spec.name,
            content=format_memory_search_results(items),
            details={"matches": [item.to_dict() for item in items]},
        )


class PrepareRepoImportTool(BaseTool):
    """PrepareRepoImportTool: normalize a local or GitHub repo source into an import plan."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="prepare_repo_import",
            description="Normalize a local or GitHub repository source into a safe import plan without cloning.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        plan = build_repo_import_plan(
            str(arguments.get("source") or ""),
            workspace=self.workspace,
            destination=str(arguments.get("destination") or ""),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=format_repo_import_plan(plan),
            details={"import_plan": plan.to_dict()},
        )


class BuildProjectPlanTool(BaseTool):
    """BuildProjectPlanTool: create a deterministic project plan from a repo blueprint."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="build_project_plan",
            description="Analyze a local repository blueprint and turn it into a task-oriented project plan.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "goal": {"type": "string"},
                    "max_files": {"type": "integer"},
                    "max_depth": {"type": "integer"},
                },
                "required": ["goal"],
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        blueprint = build_repo_blueprint(
            root,
            max_files=int(arguments.get("max_files") or 1200),
            max_depth=int(arguments.get("max_depth") or 4),
        )
        plan = build_project_plan_from_blueprint(blueprint, goal=str(arguments.get("goal") or ""))
        return ToolResult(
            tool_name=self.spec.name,
            content=format_project_plan(plan),
            details={"plan": plan.to_dict(), "blueprint": blueprint.to_dict()},
        )


class ImportRepositoryTool(BaseTool):
    """Safely import a local repo, or clone only when explicitly allowed."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="import_repository",
            description="Import a local repository into workspace imports and cache metadata. Network clone requires allow_network=true.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                    "allow_network": {"type": "boolean"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["source"],
            },
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        record = import_repository(
            str(arguments.get("source") or ""),
            workspace=self.workspace,
            destination=str(arguments.get("destination") or ""),
            allow_network=bool(arguments.get("allow_network")),
            overwrite=bool(arguments.get("overwrite")),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=format_import_record(record),
            details={"import": record},
        )


class RepoGitStatusTool(BaseTool):
    """Read git branch, status, and optional diff for a workspace path."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="repo_git_status",
            description="Inspect git branch, commit, status, and optional diff for a local repo path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "include_diff": {"type": "boolean"},
                    "max_diff_chars": {"type": "integer"},
                },
            },
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        snapshot = inspect_git_status(
            root,
            include_diff=bool(arguments.get("include_diff")),
            max_diff_chars=int(arguments.get("max_diff_chars") or 8000),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=format_git_snapshot(snapshot),
            details={"git": snapshot.to_dict()},
        )


class RepoCacheListTool(BaseTool):
    """List repositories imported through the local repo cache."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_repo_cache",
            description="List repositories imported into the workspace repo cache.",
            parameters={"type": "object", "properties": {}},
            permission_domain="read",
            requires_confirmation=False,
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        records = list_repo_cache(self.workspace)
        if records:
            content = "\n".join(f"- {item['repo_id']}: {item['imported_path']}" for item in records)
        else:
            content = "No repositories have been imported."
        return ToolResult(
            tool_name=self.spec.name,
            content=content,
            details={"imports": records},
        )


def register_repo_tools(registry, workspace: Path) -> None:
    """把仓库索引、架构分析和蓝图记忆工具注册到 ToolRegistry。"""
    registry.register(IndexRepoStructureTool(workspace), category="repo")
    registry.register(AnalyzeRepoBlueprintTool(workspace), category="repo")
    registry.register(SaveBlueprintMemoryTool(workspace), category="repo")
    registry.register(SearchBlueprintMemoryTool(workspace), category="repo")
    registry.register(PrepareRepoImportTool(workspace), category="repo")
    registry.register(ImportRepositoryTool(workspace), category="repo")
    registry.register(RepoGitStatusTool(workspace), category="repo")
    registry.register(RepoCacheListTool(workspace), category="repo")
    registry.register(BuildProjectPlanTool(workspace), category="repo")
