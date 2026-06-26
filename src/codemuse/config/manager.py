"""合并默认配置、项目配置和运行时覆盖，产生有效配置快照。"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from codemuse.config.patch import changed_paths_from_patch, merge_patch, set_path_value
from codemuse.config.runtime_overrides import runtime_overrides
from codemuse.config.schema import CodeMuseConfig, config_schema, default_config

CONFIG_DIR = ".codemuse"
CONFIG_FILE = "config.json"


@dataclass(frozen=True)
class ConfigSnapshot:
    """一次配置解析的完整快照，包含有效配置、来源和变更路径。"""
    config: CodeMuseConfig
    project_config: dict[str, Any]
    runtime_config: dict[str, Any]
    effective_config: dict[str, Any]
    source_map: dict[str, str]
    changed_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        """把 ConfigSnapshot 转成可写入文件或 API 响应的字典。"""
        return {
            "config": self.config.to_dict(),
            "project_config": deepcopy(self.project_config),
            "runtime_config": deepcopy(self.runtime_config),
            "effective_config": deepcopy(self.effective_config),
            "source_map": dict(self.source_map),
            "changed_paths": list(self.changed_paths),
            "schema": config_schema(),
        }


class ConfigManager:
    """ConfigManager：协调该领域对象的创建、查询和生命周期。"""
    def __init__(self, workspace: Path) -> None:
        """注入该管理器需要协调的配置、注册表或存储依赖。"""
        self.workspace = workspace.resolve()
        self.config_dir = self.workspace / CONFIG_DIR
        self.config_path = self.config_dir / CONFIG_FILE
        self._lock = RLock()

    def get_project_config(self) -> dict[str, Any]:
        """读取该领域的单个对象或有效快照。"""
        return self._read_project_config()

    def get_effective_config(self) -> CodeMuseConfig:
        """读取该领域的单个对象或有效快照。"""
        return self.get_snapshot().config

    def get_snapshot(self) -> ConfigSnapshot:
        """读取该领域的单个对象或有效快照。"""
        with self._lock:
            default_payload = default_config().to_dict()
            environment = _environment_config_patch()
            project = self._read_project_config()
            runtime = runtime_overrides.get(self.workspace)
            effective = merge_patch(merge_patch(merge_patch(default_payload, environment), project), runtime)
            config = CodeMuseConfig.from_dict(effective)
            return ConfigSnapshot(
                config=config,
                project_config=project,
                runtime_config=runtime,
                effective_config=effective,
                source_map=_source_map(environment, project, runtime),
                changed_paths=sorted(set(
                    changed_paths_from_patch(environment)
                    + changed_paths_from_patch(project)
                    + changed_paths_from_patch(runtime)
                )),
            )

    def patch_project_config(self, patch: dict[str, Any]) -> ConfigSnapshot:
        """将配置 patch 合并到项目配置文件，并在写入前做 schema 校验。"""
        if not isinstance(patch, dict):
            raise ValueError("Config patch must be a JSON object.")
        with self._lock:
            current = self._read_project_config()
            updated = merge_patch(current, patch)
            if not isinstance(updated, dict):
                raise ValueError("Project config must remain a JSON object.")
            CodeMuseConfig.from_dict(merge_patch(default_config().to_dict(), updated))
            self._write_project_config(updated)
            return self.get_snapshot()

    def set_path(self, path: str, value: Any) -> ConfigSnapshot:
        """把单个点路径值写入配置结构。"""
        with self._lock:
            current = self._read_project_config()
            updated = set_path_value(current, path, value)
            CodeMuseConfig.from_dict(merge_patch(default_config().to_dict(), updated))
            self._write_project_config(updated)
            return self.get_snapshot()

    def set_runtime_override(self, path: str, value: Any) -> ConfigSnapshot:
        """把单个点路径值写入运行时覆盖存储。"""
        runtime_overrides.set_path(self.workspace, path, value)
        # 运行时覆盖只影响当前进程，不写入 .codemuse/config.json。
        CodeMuseConfig.from_dict(merge_patch(default_config().to_dict(), runtime_overrides.get(self.workspace)))
        return self.get_snapshot()

    def clear_runtime_overrides(self) -> ConfigSnapshot:
        """清除当前 workspace 的进程内配置覆盖。"""
        runtime_overrides.clear(self.workspace)
        return self.get_snapshot()

    def schema(self) -> dict[str, Any]:
        """返回可展示给 CLI/Web 的配置字段说明。"""
        return config_schema()

    def _read_project_config(self) -> dict[str, Any]:
        """读取内部数据并转换为当前模块需要的结构。"""
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid CodeMuse config JSON: {self.config_path}") from exc
        if not isinstance(data, dict):
            raise ValueError("CodeMuse config must be a JSON object.")
        return data

    def _write_project_config(self, data: dict[str, Any]) -> None:
        """将内部数据写入本地存储。"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_config_manager(workspace: Path) -> ConfigManager:
    """读取该领域的单个对象或有效快照。"""
    return ConfigManager(workspace)


def config_for_workspace(workspace: Path) -> CodeMuseConfig:
    """读取 workspace 最终生效的 CodeMuseConfig。"""
    return get_config_manager(workspace).get_effective_config()



def _environment_config_patch() -> dict[str, Any]:
    """从 CODEMUSE_* 环境变量生成模型配置补丁。"""
    model: dict[str, Any] = {}
    provider = os.getenv("CODEMUSE_PROVIDER", "").strip()
    base_url = os.getenv("CODEMUSE_BASE_URL", "").strip()
    model_name = os.getenv("CODEMUSE_MODEL", "").strip()
    api_key_env = os.getenv("CODEMUSE_API_KEY_ENV", "").strip()
    if provider:
        model["provider"] = provider
    elif os.getenv("CODEMUSE_API_KEY") or base_url or model_name:
        model["provider"] = "openai_compatible"
    if model_name:
        model["model"] = model_name
    if base_url:
        model["base_url"] = base_url
    if api_key_env:
        model["api_key_env"] = api_key_env
    elif os.getenv("CODEMUSE_API_KEY"):
        model["api_key_env"] = "CODEMUSE_API_KEY"
    return {"model": model} if model else {}
def _source_map(environment: dict[str, Any], project: dict[str, Any], runtime: dict[str, Any]) -> dict[str, str]:
    """记录每个配置路径最终来自环境变量、项目配置还是运行时覆盖。"""
    source: dict[str, str] = {}
    for path in changed_paths_from_patch(environment):
        source[path] = "environment"
    for path in changed_paths_from_patch(project):
        source[path] = "project"
    for path in changed_paths_from_patch(runtime):
        source[path] = "runtime"
    return source

