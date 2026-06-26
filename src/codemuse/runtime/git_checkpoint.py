"""保存和恢复 workspace 文件快照，用于安全回退。"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

IGNORED_SNAPSHOT_DIRS = {".git", ".data", "__pycache__", ".venv", "node_modules", "dist", "build"}


class WorkspaceSnapshotManager:
    """用普通文件快照实现 Git-backed safe rewind 的教学版。"""

    def __init__(self, workspace: Path, checkpoint_root: Path) -> None:
        """保存 workspace 和 checkpoint 存储根目录。"""
        self.workspace = workspace.resolve()
        self.snapshot_root = checkpoint_root.resolve() / "snapshots"
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, checkpoint_id: str) -> dict[str, Any]:
        """复制 workspace 受控文件到 checkpoint 快照目录，并返回 manifest 摘要。"""
        snapshot_dir = self._snapshot_dir(checkpoint_id)
        if snapshot_dir.exists():
            self._assert_inside_snapshot_root(snapshot_dir)
            shutil.rmtree(snapshot_dir)
        files_dir = snapshot_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        files: list[dict[str, Any]] = []
        total_bytes = 0
        for source in sorted(self.workspace.rglob("*")):
            if not source.is_file() or self._is_ignored(source):
                continue
            relative_path = source.relative_to(self.workspace).as_posix()
            target = files_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            size = source.stat().st_size
            total_bytes += size
            files.append(
                {
                    "relative_path": relative_path,
                    "size": size,
                    "sha256": _sha256_file(source),
                }
            )

        manifest = {
            "checkpoint_id": checkpoint_id,
            "kind": "workspace_snapshot",
            "files_count": len(files),
            "total_bytes": total_bytes,
            "files": files,
        }
        (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "kind": "workspace_snapshot",
            "files_count": len(files),
            "total_bytes": total_bytes,
            "snapshot_path": str(snapshot_dir),
        }

    def restore_snapshot(self, checkpoint_id: str) -> dict[str, Any]:
        """把 workspace 恢复到指定 checkpoint 的快照状态。"""
        manifest = self._load_manifest(checkpoint_id)
        files_dir = self._snapshot_dir(checkpoint_id) / "files"
        snapshot_paths = {str(item["relative_path"]) for item in manifest.get("files", [])}

        removed_files: list[str] = []
        restored_files: list[str] = []
        for current in sorted(self.workspace.rglob("*"), reverse=True):
            if not current.is_file() or self._is_ignored(current):
                continue
            relative_path = current.relative_to(self.workspace).as_posix()
            if relative_path in snapshot_paths:
                continue
            self._assert_inside_workspace(current)
            current.unlink()
            removed_files.append(relative_path)

        for item in manifest.get("files", []):
            relative_path = str(item["relative_path"])
            source = files_dir / relative_path
            target = self._workspace_file(relative_path)
            if not source.exists():
                raise FileNotFoundError(f"Snapshot file missing: {relative_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored_files.append(relative_path)

        self._prune_empty_dirs()
        return {
            "checkpoint_id": checkpoint_id,
            "restored_workspace": True,
            "restored_files_count": len(restored_files),
            "removed_files_count": len(removed_files),
            "restored_files": restored_files[:50],
            "removed_files": removed_files[:50],
        }

    def preview_restore(self, checkpoint_id: str) -> dict[str, Any]:
        """生成 workspace 恢复预览，不写入磁盘。"""
        manifest = self._load_manifest(checkpoint_id)
        snapshot_paths = {str(item["relative_path"]) for item in manifest.get("files", [])}
        current_paths = {
            path.relative_to(self.workspace).as_posix()
            for path in self.workspace.rglob("*")
            if path.is_file() and not self._is_ignored(path)
        }
        return {
            "checkpoint_id": checkpoint_id,
            "snapshot_files_count": len(snapshot_paths),
            "current_files_count": len(current_paths),
            "will_restore_count": len(snapshot_paths),
            "will_remove_count": len(current_paths - snapshot_paths),
            "will_remove": sorted(current_paths - snapshot_paths)[:50],
        }

    def _load_manifest(self, checkpoint_id: str) -> dict[str, Any]:
        """读取指定 checkpoint 的 workspace manifest。"""
        manifest_path = self._snapshot_dir(checkpoint_id) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Workspace snapshot not found for checkpoint: {checkpoint_id}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _snapshot_dir(self, checkpoint_id: str) -> Path:
        """计算 checkpoint 快照目录。"""
        if any(part in checkpoint_id for part in ["..", "/", "\\"]):
            raise ValueError(f"Invalid checkpoint id: {checkpoint_id}")
        return self.snapshot_root / checkpoint_id

    def _workspace_file(self, relative_path: str) -> Path:
        """把 manifest 里的相对路径限制在 workspace 内。"""
        target = (self.workspace / relative_path).resolve()
        self._assert_inside_workspace(target)
        return target

    def _is_ignored(self, path: Path) -> bool:
        """判断路径是否属于不应该纳入快照的目录。"""
        relative_parts = path.relative_to(self.workspace).parts
        return any(part in IGNORED_SNAPSHOT_DIRS for part in relative_parts)

    def _prune_empty_dirs(self) -> None:
        """恢复后清理 workspace 内多余空目录，但保留受保护目录。"""
        for path in sorted(self.workspace.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if not path.is_dir() or self._is_ignored(path):
                continue
            try:
                path.rmdir()
            except OSError:
                continue

    def _assert_inside_workspace(self, path: Path) -> None:
        """确保后续删除或写入不会越过 workspace。"""
        resolved = path.resolve()
        if self.workspace not in resolved.parents and resolved != self.workspace:
            raise PermissionError(f"Snapshot path escapes workspace: {path}")

    def _assert_inside_snapshot_root(self, path: Path) -> None:
        """确保删除旧快照时只删除 checkpoint 快照目录内部内容。"""
        resolved = path.resolve()
        if self.snapshot_root not in resolved.parents and resolved != self.snapshot_root:
            raise PermissionError(f"Snapshot path escapes checkpoint root: {path}")


def _sha256_file(path: Path) -> str:
    """计算文件内容哈希，用于 manifest 记录。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
