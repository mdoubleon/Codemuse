"""Discover workspace skills without executing or materializing them."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillSearchRoot:
    """定义 SkillSearchRoot的结构化数据。"""
    path: Path
    source: str
    precedence: int = 0


@dataclass(frozen=True)
class SkillDescriptor:
    """描述 Skill 的名称、来源和元数据。"""
    name: str
    description: str
    path: Path
    source: str
    precedence: int = 0
    discovery_mode: str = "workspace_directory"
    status: str = "loaded"
    error: str = ""


def skill_search_roots(workspace: Path) -> list[SkillSearchRoot]:
    """处理 Skill搜索roots。"""
    workspace = workspace.resolve()
    return [
        SkillSearchRoot(workspace / ".codemuse" / "skills", source="project_config", precedence=0),
        SkillSearchRoot(workspace / "skills", source="project", precedence=1),
    ]


def load_skills(workspace: Path, *, search_roots: list[SkillSearchRoot] | None = None) -> dict[str, SkillDescriptor]:
    """加载skills。"""
    roots = search_roots or skill_search_roots(workspace)
    skills: dict[str, SkillDescriptor] = {}
    for root in sorted(roots, key=lambda item: item.precedence):
        if not root.path.exists():
            continue
        for path in sorted(root.path.glob("**/SKILL.md")):
            try:
                descriptor = _parse_skill_descriptor(path, root)
            except Exception as exc:
                descriptor = SkillDescriptor(
                    name=path.parent.name,
                    description=f"Invalid skill descriptor: {exc}",
                    path=path.resolve(),
                    source=root.source,
                    precedence=root.precedence,
                    discovery_mode="codemuse_project_directory",
                    status="error",
                    error=str(exc),
                )
            if descriptor.name in skills:
                continue
            skills[descriptor.name] = descriptor
    return skills


def _parse_skill_descriptor(path: Path, root: SkillSearchRoot) -> SkillDescriptor:
    """解析Skill描述符。"""
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    metadata = _frontmatter(rows)
    if metadata is None:
        metadata = _fallback_metadata(path, rows)
    name = metadata.get("name", "").strip() or path.parent.name
    description = metadata.get("description", "").strip() or name
    return SkillDescriptor(
        name=name,
        description=description,
        path=path.resolve(),
        source=root.source,
        precedence=root.precedence,
        discovery_mode="codemuse_project_directory",
    )


def _frontmatter(rows: list[str]) -> dict[str, str] | None:
    """处理 Frontmatter。"""
    if not rows or rows[0].strip() != "---":
        return None
    body: list[str] = []
    for row in rows[1:]:
        if row.strip() == "---":
            return _parse_key_values(body)
        body.append(row)
    raise ValueError("Skill frontmatter must close with ---")


def _parse_key_values(rows: list[str]) -> dict[str, str]:
    """解析键值。"""
    data: dict[str, str] = {}
    for row in rows:
        if ":" not in row:
            continue
        key, value = row.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def _fallback_metadata(path: Path, rows: list[str]) -> dict[str, str]:
    """处理 降级元数据。"""
    for row in rows:
        value = row.strip()
        if not value:
            continue
        if value.startswith("#"):
            return {"name": path.parent.name, "description": value.lstrip("#").strip()}
        return {"name": path.parent.name, "description": value}
    return {"name": path.parent.name, "description": path.parent.name}
