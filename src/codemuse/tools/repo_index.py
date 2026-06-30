"""扫描本地仓库并提取语言、入口、配置和树形概览线索。"""
from __future__ import annotations

import re
from pathlib import Path

from codemuse.domain.blueprint import RepoIndex

IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build", ".data", ".mypy_cache", ".pytest_cache"}

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".html": "HTML",
    ".css": "CSS",
    ".md": "Markdown",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
}

PACKAGE_FILE_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "cargo.toml",
    "go.mod",
    "pom.xml",
}
CONFIG_FILE_NAMES = {
    "dockerfile",
    "compose.yaml",
    "docker-compose.yml",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "tsconfig.json",
    "ruff.toml",
    "pytest.ini",
    ".env.example",
}
ENTRYPOINT_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "cli.py",
    "main.ts",
    "main.tsx",
    "index.ts",
    "index.tsx",
    "main.rs",
    "main.go",
}
AGENT_HINTS = ("agent", "tool", "memory", "rag", "retrieval", "llm", "runtime", "prompt", "session", "checkpoint")
ROUTE_HINTS = ("route", "router", "api", "server", "controller", "endpoint")


def index_local_repo(root: Path, *, repo_id: str | None = None, max_files: int = 1200, max_depth: int = 4) -> RepoIndex:
    """遍历本地仓库，统计文件、语言、重要文件和结构摘要。"""
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(str(root))

    languages: dict[str, int] = {}
    important_files: list[str] = []
    entrypoints: list[str] = []
    package_files: list[str] = []
    config_files: list[str] = []
    route_files: list[str] = []
    test_files: list[str] = []
    agent_related_files: list[str] = []
    file_count = 0
    total_size = 0
    truncated = False

    for path in sorted(root.rglob("*")):
        if _ignored(path, root):
            continue
        if not path.is_file():
            continue
        file_count += 1
        if file_count > max_files:
            truncated = True
            break
        rel = _rel(path, root)
        try:
            total_size += path.stat().st_size
        except OSError:
            pass
        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language:
            languages[language] = languages.get(language, 0) + 1
        name = path.name.lower()
        rel_lower = rel.lower()
        if name in PACKAGE_FILE_NAMES:
            package_files.append(rel)
        if name in CONFIG_FILE_NAMES or path.suffix.lower() in {".toml", ".yaml", ".yml"}:
            config_files.append(rel)
        if name in ENTRYPOINT_NAMES:
            entrypoints.append(rel)
        if any(hint in rel_lower for hint in ROUTE_HINTS):
            route_files.append(rel)
        if "test" in rel_lower or "tests" in path.parts:
            test_files.append(rel)
        if any(hint in rel_lower for hint in AGENT_HINTS):
            agent_related_files.append(rel)
        if _is_important_file(path, rel_lower):
            important_files.append(rel)

    return RepoIndex(
        repo_id=repo_id or _repo_id_from_path(root),
        root_path=str(root),
        file_count=min(file_count, max_files),
        total_size=total_size,
        languages=dict(sorted(languages.items(), key=lambda item: (-item[1], item[0]))),
        important_files=important_files[:80],
        entrypoints=entrypoints[:50],
        package_files=package_files[:50],
        config_files=config_files[:80],
        route_files=route_files[:80],
        test_files=test_files[:80],
        agent_related_files=agent_related_files[:80],
        tree_summary=_tree_summary(root, max_depth=max_depth),
        truncated=truncated,
    )


def format_repo_index(index: RepoIndex) -> str:
    """把 RepoIndex 转成适合 CLI 或模型阅读的文本报告。"""
    lines = [
        f"Repo index: {index.repo_id}",
        f"Root: {index.root_path}",
        f"Files: {index.file_count}",
        f"Total size: {index.total_size} bytes",
        "Languages: " + (", ".join(f"{name}({count})" for name, count in index.languages.items()) or "unknown"),
    ]
    _append_section(lines, "Entrypoints", index.entrypoints)
    _append_section(lines, "Package files", index.package_files)
    _append_section(lines, "Config files", index.config_files)
    _append_section(lines, "Agent-related files", index.agent_related_files)
    _append_section(lines, "Important files", index.important_files)
    lines.append("Tree summary:")
    lines.append(index.tree_summary or "(empty)")
    if index.truncated:
        lines.append("[index truncated by max_files]")
    return "\n".join(lines)


def _append_section(lines: list[str], title: str, values: list[str]) -> None:
    """将结果追加到当前会话、事件或文本集合中。"""
    if values:
        lines.append(f"{title}:")
        lines.extend(f"- {value}" for value in values[:20])


def _ignored(path: Path, root: Path) -> bool:
    """判断仓库索引时是否应该跳过该路径。"""
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in IGNORED_DIRS for part in rel_parts)


def _rel(path: Path, root: Path) -> str:
    """把绝对路径转换成仓库根目录相对的 POSIX 路径。"""
    return path.relative_to(root).as_posix()


def _is_important_file(path: Path, rel_lower: str) -> bool:
    """判断文件是否属于仓库索引的重要文件。"""
    name = path.name.lower()
    if name.startswith("readme") or name in PACKAGE_FILE_NAMES or name in CONFIG_FILE_NAMES or name in ENTRYPOINT_NAMES:
        return True
    if re.search(r"(^|/)(src|app|server|api|agent|tools|memory)(/|$)", rel_lower):
        return path.suffix.lower() in LANGUAGE_BY_SUFFIX
    return False


def _tree_summary(root: Path, *, max_depth: int) -> str:
    """生成限制深度和行数的仓库目录树摘要。"""
    lines: list[str] = []
    base_depth = len(root.parts)
    for path in sorted(root.rglob("*")):
        if _ignored(path, root):
            continue
        depth = len(path.parts) - base_depth
        if depth > max_depth:
            continue
        prefix = "  " * max(0, depth - 1)
        suffix = "/" if path.is_dir() else ""
        lines.append(f"{prefix}{path.name}{suffix}")
        if len(lines) >= 240:
            lines.append("... truncated")
            break
    return "\n".join(lines)


def _repo_id_from_path(root: Path) -> str:
    """根据仓库目录名生成稳定且安全的 repo_id。"""
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", root.name).strip("_") or "repo"
