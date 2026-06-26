"""实现基础代码工具：列文件、读文件、搜索文本和安全写文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.tools.base import BaseTool, ToolResult, ToolSpec
from codemuse.tools.effects import apply_unified_patch, replace_text_in_file

IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules", "dist", "build", ".data"}


class ListFilesTool(BaseTool):
    """ListFilesTool：列出 workspace 内文件结构的只读工具。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 ListFilesTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="list_files",
            description="List files under the current workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_depth": {"type": "integer"},
                },
            },
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 ListFilesTool 的具体动作，并返回 ToolResult。"""
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        max_depth = int(arguments.get("max_depth") or 2)
        if not root.exists():
            raise FileNotFoundError(str(root))
        lines: list[str] = []
        base_depth = len(root.parts)
        for path in sorted(root.rglob("*")):
            if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
                continue
            depth = len(path.parts) - base_depth
            if depth > max_depth:
                continue
            prefix = "  " * max(0, depth - 1)
            suffix = "/" if path.is_dir() else ""
            lines.append(f"{prefix}{path.name}{suffix}")
            if len(lines) >= 200:
                lines.append("... truncated")
                break
        return ToolResult(tool_name=self.spec.name, content="\n".join(lines), details={"path": str(root)})


class ReadFileTool(BaseTool):
    """ReadFileTool：读取 workspace 内指定文本文件的只读工具。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 ReadFileTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="read_file",
            description="Read a text file from the current workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 ReadFileTool 的具体动作，并返回 ToolResult。"""
        path = self.resolve_workspace_path(str(arguments["path"]))
        max_chars = int(arguments.get("max_chars") or 12000)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))
        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        content = text[:max_chars]
        if truncated:
            content += f"\n\n[truncated {len(text) - max_chars} characters]"
        return ToolResult(
            tool_name=self.spec.name,
            content=content,
            details={"path": str(path), "truncated": truncated},
        )


class SearchTextTool(BaseTool):
    """SearchTextTool：在 workspace 文件中搜索文本的只读工具。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 SearchTextTool 的工具名、参数 schema、权限域和副作用。"""
        return ToolSpec(
            name="search_text",
            description="Search text in workspace files.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """读取 arguments，执行 SearchTextTool 的具体动作，并返回 ToolResult。"""
        query = str(arguments["query"])
        root = self.resolve_workspace_path(str(arguments.get("path") or "."))
        limit = int(arguments.get("limit") or 30)
        matches: list[str] = []
        for path in sorted(root.rglob("*")):
            if len(matches) >= limit:
                break
            if not path.is_file() or any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if query.lower() in line.lower():
                    rel = path.relative_to(self.workspace)
                    matches.append(f"{rel}:{line_no}: {line.strip()}")
                    if len(matches) >= limit:
                        break
        return ToolResult(tool_name=self.spec.name, content="\n".join(matches) or "No matches.", details={"query": query})


class WriteFileTool(BaseTool):
    """WriteFileTool：在 workspace 内写入文本文件的有副作用工具，执行前必须经过审批。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 write_file 的目标路径、写入内容、目录创建选项和写入权限。"""
        return ToolSpec(
            name="write_file",
            description="Write UTF-8 text content to a file inside the current workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "create_dirs": {"type": "boolean"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """审批通过后把 content 写入 workspace 内目标文件，并返回写入摘要。"""
        path = self.resolve_workspace_path(str(arguments["path"]))
        content = str(arguments.get("content") or "")
        create_dirs = bool(arguments.get("create_dirs", False))
        overwrite = bool(arguments.get("overwrite", True))
        if any(part in {".git", ".data"} for part in path.relative_to(self.workspace).parts):
            raise PermissionError(f"Refusing to write managed or git-internal path: {path.relative_to(self.workspace)}")
        existed = path.exists()
        if existed and path.is_dir():
            raise IsADirectoryError(str(path))
        if existed and not overwrite:
            raise FileExistsError(str(path))
        if not path.parent.exists():
            if not create_dirs:
                raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        relative = path.relative_to(self.workspace).as_posix()
        action = "Updated" if existed else "Created"
        return ToolResult(
            tool_name=self.spec.name,
            content=f"{action} file `{relative}` with {len(content)} characters.",
            details={
                "path": str(path),
                "relative_path": relative,
                "created": not existed,
                "characters": len(content),
            },
        )


class ApplyPatchTool(BaseTool):
    """用 unified diff 修改 workspace 文件的高风险工具，执行前必须经过审批。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 apply_patch 接收 patch 文本和目录创建选项，并要求审批。"""
        return ToolSpec(
            name="apply_patch",
            description="Apply a unified diff patch to files inside the current workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "patch": {"type": "string"},
                    "create_dirs": {"type": "boolean"},
                },
                "required": ["patch"],
            },
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """审批通过后应用 unified diff，并返回被修改文件摘要。"""
        changes = apply_unified_patch(self.workspace, arguments)
        lines = [
            f"{item['operation'].title()} `{item['relative_path']}` with {item['hunks']} hunk(s)."
            for item in changes
        ]
        return ToolResult(
            tool_name=self.spec.name,
            content="\n".join(lines),
            details={"changes": changes},
        )


class ReplaceTextTool(BaseTool):
    """按旧文本定位并替换 workspace 文件内容的高风险工具，执行前必须经过审批。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 replace_text 的目标路径、旧文本、新文本和替换范围。"""
        return ToolSpec(
            name="replace_text",
            description="Replace existing text in a UTF-8 file inside the current workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                    "expected_replacements": {"type": "integer"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """审批通过后执行文本替换，并返回被修改文件摘要。"""
        summary = replace_text_in_file(self.workspace, arguments)
        return ToolResult(
            tool_name=self.spec.name,
            content=(
                f"Replaced {summary['replacements']} occurrence(s) in "
                f"`{summary['relative_path']}`."
            ),
            details=summary,
        )


def register_coding_tools(registry, workspace: Path) -> None:
    """把基础 coding tools 注册到 ToolRegistry。"""
    registry.register(ListFilesTool(workspace))
    registry.register(ReadFileTool(workspace))
    registry.register(SearchTextTool(workspace))
    registry.register(WriteFileTool(workspace))
    registry.register(ApplyPatchTool(workspace))
    registry.register(ReplaceTextTool(workspace))
