"""保存当前进程内生效的临时配置覆盖。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from codemuse.config.patch import set_path_value


class RuntimeOverrideStore:
    """保存每个工作区当前进程内的临时配置覆盖。"""
    def __init__(self) -> None:
        """初始化线程锁和按工作区划分的覆盖表。"""
        self._lock = RLock()
        self._by_workspace: dict[str, dict[str, Any]] = {}

    def get(self, workspace: Path) -> dict[str, Any]:
        """读取指定工作区的配置覆盖副本。"""
        with self._lock:
            return deepcopy(self._by_workspace.get(_key(workspace), {}))

    def set_path(self, workspace: Path, path: str, value: Any) -> dict[str, Any]:
        """把单个点路径值写入配置结构。"""
        with self._lock:
            key = _key(workspace)
            current = self._by_workspace.get(key, {})
            updated = set_path_value(current, path, value)
            self._by_workspace[key] = updated
            # 返回深拷贝，避免外部代码拿到内部字典引用后误改。
            return deepcopy(updated)

    def clear(self, workspace: Path) -> None:
        """删除指定 workspace 的运行时覆盖配置。"""
        with self._lock:
            self._by_workspace.pop(_key(workspace), None)


def _key(workspace: Path) -> str:
    """把工作区路径规范化成覆盖表 key。"""
    return str(workspace.resolve())


runtime_overrides = RuntimeOverrideStore()
