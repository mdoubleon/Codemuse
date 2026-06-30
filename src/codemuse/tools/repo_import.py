"""Normalize local and GitHub repository sources into import plans."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from codemuse.domain.repo_import import RepoImportPlan

_GITHUB_HOSTS = {"github.com", "www.github.com"}


def build_repo_import_plan(source: str, *, workspace: Path, destination: str = "") -> RepoImportPlan:
    """构建仓库导入计划。"""
    source = source.strip()
    if not source:
        raise ValueError("repo source cannot be empty")
    workspace = workspace.resolve()
    github = _parse_github_source(source)
    if github is not None:
        owner, name, branch = github
        repo_id = _repo_id(owner, name)
        recommended = _destination_path(workspace, destination, repo_id)
        return RepoImportPlan(
            source=source,
            source_type="github",
            repo_id=repo_id,
            owner=owner,
            name=name,
            branch=branch,
            clone_url=f"https://github.com/{owner}/{name}.git",
            recommended_path=str(recommended),
            requires_network=True,
            import_ready=False,
            notes=[
                "GitHub source was parsed but not cloned in this MVP.",
                "Use a future approved network/file operation to fetch this repository.",
            ],
        )

    local_path = _resolve_workspace_path(source, workspace)
    if not local_path.exists() or not local_path.is_dir():
        raise NotADirectoryError(str(local_path))
    return RepoImportPlan(
        source=source,
        source_type="local",
        repo_id=_safe_name(local_path.name),
        local_path=str(local_path),
        recommended_path=str(local_path),
        requires_network=False,
        import_ready=True,
        notes=["Local repository is already available inside the workspace."],
    )


def format_repo_import_plan(plan: RepoImportPlan) -> str:
    """格式化仓库导入计划。"""
    lines = [
        f"# Repo Import Plan: {plan.repo_id}",
        "",
        f"- source_type: {plan.source_type}",
        f"- source: {plan.source}",
        f"- requires_network: {plan.requires_network}",
        f"- import_ready: {plan.import_ready}",
    ]
    if plan.local_path:
        lines.append(f"- local_path: {plan.local_path}")
    if plan.clone_url:
        lines.append(f"- clone_url: {plan.clone_url}")
    if plan.branch:
        lines.append(f"- branch: {plan.branch}")
    if plan.recommended_path:
        lines.append(f"- recommended_path: {plan.recommended_path}")
    if plan.notes:
        lines.append("")
        lines.append("## Notes")
        lines.extend(f"- {item}" for item in plan.notes)
    return "\n".join(lines)


def _parse_github_source(source: str) -> tuple[str, str, str] | None:
    """解析github源码。"""
    shorthand = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", source)
    if shorthand:
        return shorthand.group(1), _strip_git_suffix(shorthand.group(2)), ""

    ssh = re.fullmatch(r"git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?", source)
    if ssh:
        return ssh.group(1), _strip_git_suffix(ssh.group(2)), ""

    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in _GITHUB_HOSTS:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0]
    name = _strip_git_suffix(parts[1])
    branch = ""
    if len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])
    return owner, name, branch


def _destination_path(workspace: Path, destination: str, repo_id: str) -> Path:
    """处理 目标路径path。"""
    if destination:
        return _resolve_workspace_path(destination, workspace)
    return workspace / ".data" / "codemuse" / "imports" / repo_id


def _resolve_workspace_path(raw_path: str, workspace: Path) -> Path:
    """解析工作区path。"""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if workspace not in resolved.parents and resolved != workspace:
        raise PermissionError(f"Path is outside workspace: {raw_path}")
    return resolved


def _repo_id(owner: str, name: str) -> str:
    """处理 仓库ID。"""
    return f"{_safe_name(owner)}_{_safe_name(name)}"


def _safe_name(value: str) -> str:
    """生成安全名称。"""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "repo"


def _strip_git_suffix(value: str) -> str:
    """去除Gitsuffix。"""
    return value[:-4] if value.endswith(".git") else value
