"""Safe local repository import, cache metadata, and git status helpers."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.tools.repo_import import build_repo_import_plan
from codemuse.tools.repo_index import index_local_repo

IGNORED_COPY_DIRS = {".git", ".data", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}


@dataclass(frozen=True)
class RepoGitSnapshot:
    """定义 RepoGitSnapshot的结构化数据。"""
    path: str
    is_git_repo: bool
    branch: str = ""
    commit: str = ""
    status: list[str] = field(default_factory=list)
    diff_stat: str = ""
    diff: str = ""

    def to_dict(self) -> dict[str, Any]:
        """将 RepoGitSnapshot 转换为可序列化字典。"""
        return {
            "path": self.path,
            "is_git_repo": self.is_git_repo,
            "branch": self.branch,
            "commit": self.commit,
            "status": self.status,
            "diff_stat": self.diff_stat,
            "diff": self.diff,
        }


def inspect_git_status(path: Path, *, include_diff: bool = False, max_diff_chars: int = 8000) -> RepoGitSnapshot:
    """Return git status/diff metadata for a local path, falling back cleanly outside git repos."""
    root = path.resolve()
    if not (root / ".git").exists() and _git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return RepoGitSnapshot(path=str(root), is_git_repo=False)
    branch = _git_text(root, "branch", "--show-current")
    commit = _git_text(root, "rev-parse", "--short", "HEAD")
    status = [line for line in _git_text(root, "status", "--short").splitlines() if line.strip()]
    diff_stat = _git_text(root, "diff", "--stat")
    diff = _git_text(root, "diff") if include_diff else ""
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars].rstrip() + "\n... diff truncated ..."
    return RepoGitSnapshot(
        path=str(root),
        is_git_repo=True,
        branch=branch,
        commit=commit,
        status=status,
        diff_stat=diff_stat,
        diff=diff,
    )


def import_repository(
    source: str,
    *,
    workspace: Path,
    destination: str = "",
    allow_network: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Import a local repo safely, or clone only when network is explicitly allowed."""
    root = workspace.resolve()
    plan = build_repo_import_plan(source, workspace=root, destination=destination)
    target = _import_destination(root, destination, plan.repo_id)
    if plan.requires_network and not allow_network:
        raise PermissionError("Network clone requires allow_network=true and explicit approval.")
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"Import destination already exists: {target}")
        if root not in target.resolve().parents:
            raise PermissionError(f"Import destination is outside workspace: {target}")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if plan.source_type == "local":
        source_path = Path(plan.local_path).resolve()
        if source_path == target or target in source_path.parents:
            raise ValueError("Import destination cannot be inside the source repository.")
        shutil.copytree(source_path, target, ignore=_copy_ignore)
    else:
        _clone_repository(plan.clone_url, target, branch=plan.branch, allow_network=allow_network)
    repo_index = index_local_repo(target)
    git = inspect_git_status(target)
    record = {
        "repo_id": plan.repo_id,
        "source": plan.source,
        "source_type": plan.source_type,
        "imported_path": str(target),
        "imported_at": time.time(),
        "plan": plan.to_dict(),
        "git": git.to_dict(),
        "repo_index": repo_index.to_dict(),
    }
    _write_cache_record(root, record)
    return record


def list_repo_cache(workspace: Path) -> list[dict[str, Any]]:
    """列出仓库缓存。"""
    path = _cache_index_path(workspace.resolve())
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [dict(item) for item in payload.get("imports", []) if isinstance(item, dict)]


def format_git_snapshot(snapshot: RepoGitSnapshot) -> str:
    """格式化Git快照。"""
    lines = [f"# Git Status: {snapshot.path}", "", f"- is_git_repo: {snapshot.is_git_repo}"]
    if snapshot.branch:
        lines.append(f"- branch: {snapshot.branch}")
    if snapshot.commit:
        lines.append(f"- commit: {snapshot.commit}")
    lines.append(f"- changed_files: {len(snapshot.status)}")
    if snapshot.status:
        lines.append("")
        lines.append("## Status")
        lines.extend(f"- {item}" for item in snapshot.status)
    if snapshot.diff_stat:
        lines.append("")
        lines.append("## Diff Stat")
        lines.append(snapshot.diff_stat)
    if snapshot.diff:
        lines.append("")
        lines.append("## Diff")
        lines.append(snapshot.diff)
    return "\n".join(lines)


def format_import_record(record: dict[str, Any]) -> str:
    """格式化导入记录。"""
    lines = [
        f"# Imported Repository: {record['repo_id']}",
        "",
        f"- source_type: {record['source_type']}",
        f"- source: {record['source']}",
        f"- imported_path: {record['imported_path']}",
        f"- files_indexed: {record['repo_index'].get('file_count', 0)}",
    ]
    git = record.get("git", {})
    if git.get("is_git_repo"):
        lines.append(f"- branch: {git.get('branch') or '-'}")
        lines.append(f"- commit: {git.get('commit') or '-'}")
    return "\n".join(lines)


def _clone_repository(clone_url: str, target: Path, *, branch: str, allow_network: bool) -> None:
    """处理 clonerepository。"""
    if not allow_network:
        raise PermissionError("Network clone requires allow_network=true.")
    command = ["git", "clone", "--depth", "1"]
    if branch:
        command.extend(["--branch", branch])
    command.extend([clone_url, str(target)])
    completed = subprocess.run(command, text=True, capture_output=True, timeout=180, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "git clone failed")


def _git_text(root: Path, *args: str) -> str:
    """处理 Git文本。"""
    result = _git(root, *args)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """处理 Git。"""
    return subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, timeout=10, check=False)


def _import_destination(workspace: Path, destination: str, repo_id: str) -> Path:
    """处理 导入目标路径。"""
    target = Path(destination) if destination else Path("imports") / repo_id
    if not target.is_absolute():
        target = workspace / target
    resolved = target.resolve()
    if workspace not in resolved.parents and resolved != workspace:
        raise PermissionError(f"Import destination is outside workspace: {destination}")
    return resolved


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    """处理 copyignore。"""
    return {name for name in names if name in IGNORED_COPY_DIRS}


def _cache_index_path(workspace: Path) -> Path:
    """处理 缓存索引path。"""
    return workspace / ".data" / "codemuse" / "repo_cache" / "imports.json"


def _write_cache_record(workspace: Path, record: dict[str, Any]) -> None:
    """写入缓存记录。"""
    path = _cache_index_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = list_repo_cache(workspace)
    existing = [item for item in existing if item.get("repo_id") != record["repo_id"]]
    existing.append(record)
    path.write_text(json.dumps({"imports": existing}, ensure_ascii=False, indent=2), encoding="utf-8")
