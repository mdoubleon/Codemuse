"""Discover workspace extension manifests without importing their code."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExtensionSearchRoot:
    """定义 ExtensionSearchRoot的结构化数据。"""
    path: Path
    source: str
    precedence: int = 0


@dataclass(frozen=True)
class ExtensionDescriptor:
    """描述 Extension 的名称、来源和元数据。"""
    name: str
    description: str
    path: Path
    source: str
    precedence: int = 0
    entrypoint: str | None = None
    provides: list[str] = field(default_factory=list)
    version: str = ""
    status: str = "loaded"
    error: str = ""


def extension_search_roots(workspace: Path) -> list[ExtensionSearchRoot]:
    """处理 扩展搜索roots。"""
    workspace = workspace.resolve()
    return [
        ExtensionSearchRoot(workspace / ".codemuse" / "extensions", source="project_config", precedence=0),
        ExtensionSearchRoot(workspace / "extensions", source="project", precedence=1),
    ]


def load_extensions(
    workspace: Path,
    *,
    search_roots: list[ExtensionSearchRoot] | None = None,
) -> dict[str, ExtensionDescriptor]:
    """加载extensions。"""
    roots = search_roots or extension_search_roots(workspace)
    extensions: dict[str, ExtensionDescriptor] = {}
    for root in sorted(roots, key=lambda item: item.precedence):
        if not root.path.exists():
            continue
        for path in _iter_manifest_files(root.path):
            descriptor = _parse_extension_descriptor(path, root)
            if descriptor.name in extensions:
                continue
            extensions[descriptor.name] = descriptor
    return extensions


def _iter_manifest_files(root: Path) -> list[Path]:
    """遍历清单文件。"""
    direct = [root / "EXTENSION.json", root / "extension.json"]
    for path in direct:
        if path.exists():
            return [path]
    found: list[Path] = []
    for name in ("EXTENSION.json", "extension.json"):
        found.extend(root.glob(f"**/{name}"))
    return sorted(set(found))


def _parse_extension_descriptor(path: Path, root: ExtensionSearchRoot) -> ExtensionDescriptor:
    """解析扩展描述符。"""
    extension_dir = path.parent.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("extension manifest must be a JSON object")
        name = _string(payload.get("name")) or extension_dir.name
        description = _string(payload.get("description")) or name
        entrypoint = _string(payload.get("entrypoint")) or None
        version = _string(payload.get("version"))
        provides = _string_list(payload.get("provides"))
        return ExtensionDescriptor(
            name=name,
            description=description,
            path=extension_dir,
            source=root.source,
            precedence=root.precedence,
            entrypoint=entrypoint,
            provides=provides,
            version=version,
        )
    except Exception as exc:
        return ExtensionDescriptor(
            name=extension_dir.name,
            description=f"Invalid extension manifest: {exc}",
            path=extension_dir,
            source=root.source,
            precedence=root.precedence,
            status="error",
            error=str(exc),
        )


def _string(value: Any) -> str:
    """处理 string。"""
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    """处理 string列表。"""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
