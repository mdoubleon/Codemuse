"""提供配置合并、点路径写入和变更路径提取工具函数。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def merge_patch(target: Any, patch: Any) -> Any:
    """按 JSON merge patch 思路把 patch 递归合并到 target。"""
    if not isinstance(patch, dict):
        return deepcopy(patch)
    result = deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
            continue
        result[key] = merge_patch(result.get(key), value)
    return result


def set_path_value(target: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """按 a.b.c 点路径在嵌套字典中写入值。"""
    result = deepcopy(target)
    parts = _path_parts(path)
    cursor = result
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = deepcopy(value)
    return result


def changed_paths_from_patch(patch: Any, prefix: str = "") -> list[str]:
    """从配置 patch 中提取所有被修改的点路径。"""
    if not isinstance(patch, dict):
        return [prefix] if prefix else []
    paths: list[str] = []
    for key, value in patch.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            paths.extend(changed_paths_from_patch(value, path))
        else:
            paths.append(path)
    return paths


def _path_parts(path: str) -> list[str]:
    """根据标识计算本地存储路径。"""
    parts = [part.strip() for part in path.split(".") if part.strip()]
    if not parts:
        raise ValueError("Config path cannot be empty.")
    # 点路径是配置层的公共约定，例如 runtime.max_turns。
    return parts
