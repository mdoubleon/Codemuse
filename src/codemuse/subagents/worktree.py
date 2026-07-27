"""Git worktree isolation and reviewable patch artifact support."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


class WorktreeUnavailable(RuntimeError):
    pass


@dataclass
class WorktreeHandle:
    run_id: str
    agent: str
    worktree_path: str
    source_head: str
    baseline_commit: str
    dirty_context_digest: str


@dataclass
class PatchArtifact:
    artifact_id: str
    run_id: str
    agent: str
    worktree_path: str
    patch_path: str
    source_head: str
    baseline_commit: str
    changed_paths: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = "staged"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class WorktreeManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".data" / "codemuse" / "worktrees"
        self.artifact_root = self.workspace / ".data" / "codemuse" / "patch-artifacts"

    def is_available(self) -> bool:
        result = self._git(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"

    def create(self, *, run_id: str, agent: str) -> WorktreeHandle:
        if not self.is_available():
            raise WorktreeUnavailable("workspace is not a Git repository")
        if not run_id or any(char in run_id for char in ("/", "\\", "..")):
            raise ValueError("Invalid worktree run_id")
        if not agent or any(char in agent for char in ("/", "\\", "..")):
            raise ValueError("Invalid worktree agent")
        source_head = self._stdout(["rev-parse", "HEAD"])
        path = (self.root / run_id / agent).resolve()
        if path.exists():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._git(["worktree", "add", "--detach", str(path), source_head])
        dirty = self._git(["diff", "--binary", "HEAD", "--"], check=False).stdout or ""
        untracked = self._stdout(["ls-files", "--others", "--exclude-standard"])
        digest = hashlib.sha256((dirty + "\0" + untracked).encode("utf-8", errors="replace")).hexdigest()
        if dirty:
            self._git(["apply", "--binary", "--whitespace=nowarn", "-"], cwd=path, input_text=dirty, check=False)
        for relative in [item for item in untracked.splitlines() if item and not item.startswith(".data/")]:
            source = self.workspace / relative
            target = path / relative
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        self._git(["add", "-A"], cwd=path)
        self._git(["-c", "user.name=codemuse", "-c", "user.email=codemuse@example.invalid", "commit", "--allow-empty", "-m", "codemuse isolated baseline"], cwd=path)
        baseline = self._stdout(["rev-parse", "HEAD"], cwd=path)
        return WorktreeHandle(run_id, agent, str(path), source_head, baseline, digest)

    def finalize(self, handle: WorktreeHandle) -> PatchArtifact | None:
        path = Path(handle.worktree_path)
        self._git(["add", "-N", "--", "."], cwd=path, check=False)
        diff = self._git(["diff", "--binary", handle.baseline_commit, "--"], cwd=path, check=False).stdout or ""
        changed = [line.strip() for line in (self._git(["diff", "--name-only", handle.baseline_commit, "--"], cwd=path, check=False).stdout or "").splitlines() if line.strip()]
        if not diff.strip() and not changed:
            return None
        artifact_id = uuid.uuid4().hex
        destination = self.artifact_root / handle.run_id
        destination.mkdir(parents=True, exist_ok=True)
        patch_path = destination / f"{artifact_id}.patch"
        patch_path.write_text(diff, encoding="utf-8")
        artifact = PatchArtifact(artifact_id, handle.run_id, handle.agent, str(path), str(patch_path), handle.source_head, handle.baseline_commit, changed)
        (destination / f"{artifact_id}.json").write_text(json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return artifact

    def apply_check(self, artifact: PatchArtifact) -> bool:
        return self._git(["apply", "--check", artifact.patch_path], check=False).returncode == 0

    def apply(self, artifact: PatchArtifact) -> bool:
        result = self._git(["apply", artifact.patch_path], check=False)
        return result.returncode == 0

    def _stdout(self, args: list[str], *, cwd: Path | None = None) -> str:
        return (self._git(args, cwd=cwd, check=False).stdout or "").strip()

    def _git(self, args: list[str], *, cwd: Path | None = None, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(["git", *args], cwd=str((cwd or self.workspace).resolve()), input=input_text, capture_output=True, text=True, check=False)
        if check and result.returncode != 0:
            raise WorktreeUnavailable((result.stderr or result.stdout or "git command failed").strip())
        return result


__all__ = ["PatchArtifact", "WorktreeHandle", "WorktreeManager", "WorktreeUnavailable"]
