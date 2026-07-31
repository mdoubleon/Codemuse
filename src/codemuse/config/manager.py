"""合并默认配置、项目配置和运行时覆盖，产生有效配置快照。"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

from codemuse.config.patch import changed_paths_from_patch, merge_patch, set_path_value
from codemuse.config.runtime_overrides import runtime_overrides
from codemuse.config.schema import CodeMuseConfig, ConfigValidationError, config_schema, default_config

CONFIG_DIR = ".codemuse"
CONFIG_FILE = "config.json"
USER_CONFIG_PATH_ENV = "CODEMUSE_USER_CONFIG_PATH"
TRUST_WORKSPACE_MODEL_CONFIG_ENV = "CODEMUSE_TRUST_WORKSPACE_MODEL_CONFIG"

# A repository may be opened before its contents are trusted. These fields
# decide where an existing environment secret is sent, so they cannot come
# from repository-local configuration by default.
_WORKSPACE_RESTRICTED_MODEL_FIELDS = frozenset({"provider", "base_url", "api_key_env"})
_WORKSPACE_MODEL_BEHAVIOR_FIELDS = frozenset({"model", "temperature", "max_tokens"})


@dataclass(frozen=True)
class ConfigSnapshot:
    """一次配置解析的完整快照，包含有效配置、来源和变更路径。"""
    config: CodeMuseConfig
    project_config: dict[str, Any]
    runtime_config: dict[str, Any]
    effective_config: dict[str, Any]
    source_map: dict[str, str]
    changed_paths: list[str]
    user_config: dict[str, Any] = field(default_factory=dict)
    ignored_project_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """把 ConfigSnapshot 转成可写入文件或 API 响应的字典。"""
        return {
            "config": self.config.to_dict(),
            "project_config": deepcopy(self.project_config),
            "user_config": deepcopy(self.user_config),
            "runtime_config": deepcopy(self.runtime_config),
            "effective_config": deepcopy(self.effective_config),
            "source_map": dict(self.source_map),
            "changed_paths": list(self.changed_paths),
            "ignored_project_paths": list(self.ignored_project_paths),
            "schema": config_schema(),
        }


class ConfigManager:
    """负责加载、合并、更新 workspace 的 CodeMuse 配置。"""
    def __init__(self, workspace: Path, *, user_config_path: Path | None = None) -> None:
        """初始化配置目录路径和并发读写锁。"""
        self.workspace = workspace.resolve()
        self.config_dir = self.workspace / CONFIG_DIR
        self.config_path = self.config_dir / CONFIG_FILE
        configured_user_path = user_config_path if user_config_path is not None else _default_user_config_path()
        self.user_config_path = configured_user_path.expanduser().resolve() if configured_user_path is not None else None
        self._lock = RLock()

    def get_project_config(self) -> dict[str, Any]:
        """读取 workspace 项目配置文件中的配置内容。"""
        return self._read_project_config()

    def get_effective_config(self) -> CodeMuseConfig:
        """返回合并默认值、项目配置和运行时覆盖后的有效配置。"""
        return self.get_snapshot().config

    def get_snapshot(self) -> ConfigSnapshot:
        """返回包含配置来源和有效配置的快照。"""
        with self._lock:
            environment = _environment_config_patch()
            project = self._read_project_config()
            user = self._read_user_config()
            runtime = runtime_overrides.get(self.workspace)
            effective_project, ignored_project_paths = _workspace_config_patch(
                project,
                trusted_model_connection=_has_trusted_model_connection(user, environment, runtime),
            )
            config = CodeMuseConfig.from_dict(
                _merged_config_payload(
                    user=user,
                    environment=environment,
                    project=effective_project,
                    runtime=runtime,
                )
            )
            return ConfigSnapshot(
                config=config,
                project_config=project,
                user_config=user,
                runtime_config=runtime,
                effective_config=config.to_dict(),
                source_map=_source_map(user, environment, effective_project, runtime),
                changed_paths=sorted(set(
                    changed_paths_from_patch(user)
                    + changed_paths_from_patch(environment)
                    + changed_paths_from_patch(effective_project)
                    + changed_paths_from_patch(runtime)
                )),
                ignored_project_paths=ignored_project_paths,
            )

    def patch_project_config(self, patch: dict[str, Any]) -> ConfigSnapshot:
        """将配置 patch 合并到项目配置文件，并在写入前做 schema 校验。"""
        if not isinstance(patch, dict):
            raise ValueError("Config patch must be a JSON object.")
        _assert_workspace_patch_is_safe(patch)
        with self._lock:
            current = self._read_project_config()
            updated = merge_patch(current, patch)
            if not isinstance(updated, dict):
                raise ValueError("Project config must remain a JSON object.")
            effective_project, _ignored = _workspace_config_patch(updated)
            CodeMuseConfig.from_dict(_merged_config_payload(project=effective_project))
            self._write_project_config(updated)
            return self.get_snapshot()

    def set_path(self, path: str, value: Any) -> ConfigSnapshot:
        """把单个点路径值写入配置结构。"""
        _assert_workspace_path_is_safe(path, value)
        with self._lock:
            current = self._read_project_config()
            updated = set_path_value(current, path, value)
            effective_project, _ignored = _workspace_config_patch(updated)
            CodeMuseConfig.from_dict(_merged_config_payload(project=effective_project))
            self._write_project_config(updated)
            return self.get_snapshot()

    def set_runtime_override(self, path: str, value: Any) -> ConfigSnapshot:
        """把单个点路径值写入运行时覆盖存储。"""
        with self._lock:
            runtime = set_path_value(runtime_overrides.get(self.workspace), path, value)
            user = self._read_user_config()
            environment = _environment_config_patch()
            project, _ignored = _workspace_config_patch(
                self._read_project_config(),
                trusted_model_connection=_has_trusted_model_connection(user, environment, runtime),
            )
            CodeMuseConfig.from_dict(
                _merged_config_payload(
                    user=user,
                    environment=environment,
                    project=project,
                    runtime=runtime,
                )
            )
            runtime_overrides.set_path(self.workspace, path, value)
        # Runtime overrides only affect the current process and are not written to the workspace.
        return self.get_snapshot()

    def clear_runtime_overrides(self) -> ConfigSnapshot:
        """清除当前 workspace 的进程内配置覆盖。"""
        runtime_overrides.clear(self.workspace)
        return self.get_snapshot()

    def schema(self) -> dict[str, Any]:
        """返回可展示给 CLI/Web 的配置字段说明。"""
        return config_schema()

    def set_user_model_config(self, model: dict[str, Any]) -> ConfigSnapshot:
        """Persist an explicitly selected model connection outside the workspace."""
        if not isinstance(model, dict):
            raise ValueError("User model config must be a JSON object.")
        with self._lock:
            payload = {"model": deepcopy(model)}
            CodeMuseConfig.from_dict(payload)
            self._write_user_config(payload)
            return self.get_snapshot()

    def _read_project_config(self) -> dict[str, Any]:
        """读取并校验 workspace 中的项目配置 JSON。"""
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid CodeMuse config JSON: {self.config_path}") from exc
        if not isinstance(data, dict):
            raise ValueError("CodeMuse config must be a JSON object.")
        return data

    def _read_user_config(self) -> dict[str, Any]:
        """Read the user-owned model connection config, if configured."""
        if self.user_config_path is None or not self.user_config_path.exists():
            return {}
        try:
            data = json.loads(self.user_config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid CodeMuse user config JSON: {self.user_config_path}") from exc
        if not isinstance(data, dict):
            raise ValueError("CodeMuse user config must be a JSON object.")
        unknown_keys = sorted(set(data) - {"model"})
        if unknown_keys:
            raise ValueError(f"Unsupported CodeMuse user config field: {unknown_keys[0]}")
        model = data.get("model")
        if not isinstance(model, dict):
            raise ValueError("CodeMuse user config must contain a model object.")
        CodeMuseConfig.from_dict({"model": model})
        return data

    def _write_project_config(self, data: dict[str, Any]) -> None:
        """把项目配置字典写回 .codemuse/config.json。"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_user_config(self, data: dict[str, Any]) -> None:
        """Write user-owned model configuration without placing it in a repository."""
        if self.user_config_path is None:
            raise RuntimeError(
                "Unable to determine a user config location; set CODEMUSE_USER_CONFIG_PATH explicitly."
            )
        self.user_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def get_config_manager(workspace: Path, *, user_config_path: Path | None = None) -> ConfigManager:
    """为指定 workspace 创建配置管理器。"""
    return ConfigManager(workspace, user_config_path=user_config_path)


def config_for_workspace(workspace: Path) -> CodeMuseConfig:
    """返回 workspace 当前生效的 CodeMuse 配置。"""
    return get_config_manager(workspace).get_effective_config()


def _merged_config_payload(
    *,
    user: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge configuration layers while deferring the provider-specific model default."""
    payload = _default_config_payload()
    for patch in (user, environment, project, runtime):
        if patch:
            payload = merge_patch(payload, patch)
    return payload


def _default_user_config_path() -> Path | None:
    """Return a user-owned config path, never a path inside the workspace."""
    configured = os.getenv(USER_CONFIG_PATH_ENV, "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        root = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
        if root:
            return Path(root) / "CodeMuse" / CONFIG_FILE
    xdg_root = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg_root:
        return Path(xdg_root) / "codemuse" / CONFIG_FILE
    try:
        home = Path.home()
    except RuntimeError:
        # Do not fall back to the current workspace: it may be the untrusted
        # repository currently being opened.
        return None
    return home / ".config" / "codemuse" / CONFIG_FILE


def _workspace_config_patch(
    project: dict[str, Any],
    *,
    trusted_model_connection: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Strip connection settings from an untrusted repository config."""
    if _workspace_model_config_is_trusted():
        return deepcopy(project), []

    effective = deepcopy(project)
    model = effective.get("model")
    if model is None:
        # A merge-patch deletion of the model object could otherwise remove a
        # trusted provider, endpoint, or API-key environment variable.
        effective.pop("model", None)
        return effective, ["model"] if "model" in project else []
    if not isinstance(model, dict):
        return effective, []

    ignored = []
    blocked_fields = _WORKSPACE_RESTRICTED_MODEL_FIELDS
    if trusted_model_connection:
        # A repository-selected model or token limit can materially increase
        # spend or alter request behavior for a user-selected live provider.
        blocked_fields = blocked_fields | _WORKSPACE_MODEL_BEHAVIOR_FIELDS
    for field in blocked_fields:
        if field in model:
            model.pop(field)
            ignored.append(f"model.{field}")
    if not model:
        effective.pop("model", None)
    return effective, sorted(ignored)


def _has_trusted_model_connection(*patches: dict[str, Any]) -> bool:
    """Return whether user, environment, or runtime selected a live model connection."""
    for patch in patches:
        model = patch.get("model") if isinstance(patch, dict) else None
        if not isinstance(model, dict):
            continue
        provider = model.get("provider")
        if isinstance(provider, str) and provider and provider != "fake":
            return True
        if model.get("base_url") or model.get("api_key_env"):
            return True
    return False


def _workspace_model_config_is_trusted() -> bool:
    """Allow an explicit migration opt-in for a local, trusted workspace."""
    return os.getenv(TRUST_WORKSPACE_MODEL_CONFIG_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _assert_workspace_patch_is_safe(patch: dict[str, Any]) -> None:
    if _workspace_model_config_is_trusted():
        return
    model = patch.get("model")
    if isinstance(model, dict):
        blocked = sorted(_WORKSPACE_RESTRICTED_MODEL_FIELDS.intersection(model))
        if blocked:
            _raise_workspace_connection_field_error(blocked)


def _assert_workspace_path_is_safe(path: str, value: Any) -> None:
    if _workspace_model_config_is_trusted():
        return
    normalized = path.strip()
    if normalized in {f"model.{field}" for field in _WORKSPACE_RESTRICTED_MODEL_FIELDS}:
        _raise_workspace_connection_field_error([normalized.removeprefix("model.")])
    if normalized == "model" and isinstance(value, dict):
        _assert_workspace_patch_is_safe({"model": value})


def _raise_workspace_connection_field_error(fields: list[str]) -> None:
    names = ", ".join(f"model.{field}" for field in fields)
    raise ConfigValidationError(
        f"Workspace configuration cannot set {names}; use model selection, user configuration, "
        "environment variables, or a runtime override."
    )


def _default_config_payload() -> dict[str, Any]:
    """Keep the model identifier absent until the selected provider is known."""
    payload = default_config().to_dict()
    model = dict(payload["model"])
    model.pop("model", None)
    payload["model"] = model
    return payload



def _environment_config_patch() -> dict[str, Any]:
    """从 CODEMUSE_* 环境变量生成模型配置补丁。"""
    model: dict[str, Any] = {}
    provider = os.getenv("CODEMUSE_PROVIDER", "").strip()
    base_url = os.getenv("CODEMUSE_BASE_URL", "").strip()
    model_name = os.getenv("CODEMUSE_MODEL", "").strip()
    api_key_env = os.getenv("CODEMUSE_API_KEY_ENV", "").strip()
    deepseek_api_key_present = bool(os.getenv("DEEPSEEK_API_KEY"))
    selected_provider = provider
    if provider:
        model["provider"] = provider
    elif os.getenv("CODEMUSE_API_KEY") or base_url or model_name:
        selected_provider = "openai_compatible"
        model["provider"] = selected_provider
    elif deepseek_api_key_present:
        selected_provider = "deepseek"
        model["provider"] = selected_provider
    if model_name:
        model["model"] = model_name
    elif selected_provider == "deepseek":
        # Avoid inheriting the fake-provider model name when DeepSeek is inferred from its key.
        model["model"] = "deepseek-chat"
    if base_url:
        model["base_url"] = base_url
    if api_key_env:
        model["api_key_env"] = api_key_env
    elif selected_provider == "deepseek":
        model["api_key_env"] = "DEEPSEEK_API_KEY"
    elif os.getenv("CODEMUSE_API_KEY"):
        model["api_key_env"] = "CODEMUSE_API_KEY"
    return {"model": model} if model else {}
def _source_map(
    user: dict[str, Any],
    environment: dict[str, Any],
    project: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, str]:
    """记录每个配置路径最终来自环境变量、项目配置还是运行时覆盖。"""
    source: dict[str, str] = {}
    for path in changed_paths_from_patch(user):
        source[path] = "user"
    for path in changed_paths_from_patch(environment):
        source[path] = "environment"
    for path in changed_paths_from_patch(project):
        source[path] = "project"
    for path in changed_paths_from_patch(runtime):
        source[path] = "runtime"
    return source

