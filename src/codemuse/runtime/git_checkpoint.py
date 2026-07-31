"""保存和恢复 workspace 文件快照，用于安全回退。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

IGNORED_SNAPSHOT_DIRS = {".git", ".data", "__pycache__", ".venv", "node_modules", "dist", "build"}
MAX_SNAPSHOT_FILES = 20_000
MAX_SNAPSHOT_BYTES = 1024 * 1024 * 1024


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
            if self._is_ignored(source):
                continue
            if source.is_symlink():
                raise PermissionError(f"Refusing to snapshot symbolic link: {source.relative_to(self.workspace)}")
            if not source.is_file():
                continue
            relative_path = source.relative_to(self.workspace).as_posix()
            size = source.stat().st_size
            if len(files) + 1 > MAX_SNAPSHOT_FILES or total_bytes + size > MAX_SNAPSHOT_BYTES:
                raise RuntimeError("Workspace snapshot exceeds the configured file or byte limit")
            target = files_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            total_bytes += size
            files.append(
                {
                    "relative_path": relative_path,
                    "size": size,
                    "sha256": _sha256_file(source),
                }
            )

        git_metadata = self._git_metadata()
        checkpoint_commit = self._commit_snapshot(files_dir, checkpoint_id)
        if checkpoint_commit:
            git_metadata = {**git_metadata, "checkpoint_commit": checkpoint_commit}
        manifest = {
            "checkpoint_id": checkpoint_id,
            "kind": "git_checkpoint" if checkpoint_commit else "workspace_snapshot",
            "files_count": len(files),
            "total_bytes": total_bytes,
            "files": files,
        }
        if git_metadata.get("available"):
            manifest["git"] = git_metadata
        manifest_path = snapshot_dir / "manifest.json"
        temporary_manifest = snapshot_dir / f".{manifest_path.name}.tmp"
        with temporary_manifest.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_manifest, manifest_path)
        return {
            "kind": manifest["kind"],
            "files_count": len(files),
            "total_bytes": total_bytes,
            "snapshot_path": str(snapshot_dir),
            "git": git_metadata,
        }

    def describe_workspace(self) -> dict[str, Any]:
        """Return read-only Git identity and dirty-worktree metadata when available."""
        return self._git_metadata()

    def restore_snapshot(self, checkpoint_id: str) -> dict[str, Any]:
        """把 workspace 恢复到指定 checkpoint 的快照状态。"""
        manifest = self._load_manifest(checkpoint_id)
        files_dir = self._snapshot_dir(checkpoint_id) / "files"
        snapshot_paths = {str(item["relative_path"]) for item in manifest.get("files", [])}
        self._validate_snapshot_files(manifest, files_dir)
        rollback_dir = Path(tempfile.mkdtemp(prefix=f"rewind-{checkpoint_id}-", dir=self.snapshot_root))
        rollback_files = self._backup_workspace(rollback_dir)
        removed_files: list[str] = []
        restored_files: list[str] = []
        try:
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
                if target.is_symlink():
                    raise PermissionError(f"Refusing to overwrite symbolic link during rewind: {relative_path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                restored_files.append(relative_path)
        except Exception:
            self._restore_backup(rollback_dir, rollback_files)
            raise
        finally:
            shutil.rmtree(rollback_dir, ignore_errors=True)

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
            "snapshot_kind": manifest.get("kind", "workspace_snapshot"),
            "snapshot_git": manifest.get("git", {"available": False}),
            "current_git": self._git_metadata(),
        }

    def _validate_snapshot_files(self, manifest: dict[str, Any], files_dir: Path) -> None:
        for item in manifest.get("files", []):
            relative_path = str(item.get("relative_path") or "")
            source = (files_dir / relative_path).resolve()
            files_root = files_dir.resolve()
            if files_root not in source.parents:
                raise PermissionError(f"Snapshot manifest path escapes files root: {relative_path}")
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(f"Snapshot file missing or unsafe: {relative_path}")
            expected_size = int(item.get("size") or 0)
            expected_hash = str(item.get("sha256") or "")
            if source.stat().st_size != expected_size or _sha256_file(source) != expected_hash:
                raise RuntimeError(f"Snapshot file failed integrity validation: {relative_path}")
            target = self.workspace / relative_path
            if target.is_symlink():
                raise PermissionError(f"Workspace target is a symbolic link: {relative_path}")
            self._workspace_file(relative_path)

    def _backup_workspace(self, destination: Path) -> list[str]:
        paths: list[str] = []
        for source in sorted(self.workspace.rglob("*")):
            if self._is_ignored(source):
                continue
            if source.is_symlink():
                raise PermissionError(f"Refusing transactional rewind with symbolic link: {source.relative_to(self.workspace)}")
            if not source.is_file():
                continue
            relative_path = source.relative_to(self.workspace).as_posix()
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            paths.append(relative_path)
        return paths

    def _restore_backup(self, backup_dir: Path, backup_files: list[str]) -> None:
        for current in sorted(self.workspace.rglob("*"), reverse=True):
            if current.is_file() and not self._is_ignored(current):
                current.unlink()
        for relative_path in backup_files:
            source = backup_dir / relative_path
            target = self._workspace_file(relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    @staticmethod
    def _commit_snapshot(files_dir: Path, checkpoint_id: str) -> str:
        if shutil.which("git") is None:
            return ""
        commands = [
            ["git", "init", "--quiet"],
            ["git", "add", "-A"],
            [
                "git", "-c", "user.name=codemuse", "-c", "user.email=codemuse@example.invalid",
                "commit", "--quiet", "--allow-empty", "-m", f"CodeMuse checkpoint {checkpoint_id}",
            ],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=files_dir, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                return ""
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=files_dir, capture_output=True, text=True, check=False)
        return (result.stdout or "").strip() if result.returncode == 0 else ""

    def _load_manifest(self, checkpoint_id: str) -> dict[str, Any]:
        """读取指定 checkpoint 的 workspace manifest。"""
        manifest_path = self._snapshot_dir(checkpoint_id) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Workspace snapshot not found for checkpoint: {checkpoint_id}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid workspace snapshot manifest: {checkpoint_id}") from exc
        if not isinstance(manifest, dict):
            raise ValueError(f"Workspace snapshot manifest must be an object: {checkpoint_id}")
        if str(manifest.get("checkpoint_id") or "") != checkpoint_id:
            raise ValueError(f"Workspace snapshot does not match checkpoint: {checkpoint_id}")
        if not isinstance(manifest.get("files"), list):
            raise ValueError(f"Workspace snapshot manifest has no file list: {checkpoint_id}")
        return manifest

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

    def _git_metadata(self) -> dict[str, Any]:
        """Capture Git state without mutating the user's repository.

        The file snapshot remains the source of truth for restore because it also
        handles non-Git workspaces and untracked files. Git metadata makes the
        checkpoint auditable and allows callers to show the original branch/HEAD.
        """
        if not self._git_available():
            return {"available": False}
        head = self._git_stdout(["rev-parse", "HEAD"])
        branch = self._git_stdout(["symbolic-ref", "--short", "-q", "HEAD"]) or "HEAD"
        status = self._git_stdout(["status", "--porcelain=v1", "--untracked-files=all"])
        diff = self._git_stdout(["diff", "--binary", "HEAD", "--"])
        untracked = self._git_stdout(["ls-files", "--others", "--exclude-standard"])
        dirty_digest = hashlib.sha256(
            (diff + "\0" + untracked).encode("utf-8", errors="replace")
        ).hexdigest()
        return {
            "available": True,
            "head": head,
            "branch": branch,
            "dirty": bool(status.strip()),
            "dirty_context_digest": dirty_digest,
            "changed_paths": [line[3:] for line in status.splitlines() if len(line) >= 4],
            "untracked_paths": [line for line in untracked.splitlines() if line],
        }

    def _git_available(self) -> bool:
        result = self._git(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"

    def _git_stdout(self, args: list[str]) -> str:
        result = self._git(args, check=False)
        return (result.stdout or "").strip()

    def _git(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
        return result

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
