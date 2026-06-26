"""编排会话与 workspace 的安全回退。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codemuse.runtime.git_checkpoint import WorkspaceSnapshotManager


@dataclass
class SafeRewindPreview:
    """描述一次 workspace 回退会影响哪些文件。"""

    checkpoint_id: str
    restore_preview: dict[str, Any] = field(default_factory=dict)
    warning_messages: list[str] = field(default_factory=list)


class SafeRewindOrchestrator:
    """把 checkpoint 快照恢复包装成可预览、可执行的回退入口。"""

    def __init__(self, workspace: Path, checkpoint_root: Path) -> None:
        """保存 workspace 和 checkpoint 存储根目录。"""
        self.snapshot_manager = WorkspaceSnapshotManager(workspace, checkpoint_root)

    def preview_rewind(self, checkpoint_id: str) -> SafeRewindPreview:
        """生成 workspace 回退预览，不修改文件。"""
        preview = self.snapshot_manager.preview_restore(checkpoint_id)
        warnings: list[str] = []
        if preview.get("will_remove_count", 0):
            warnings.append("Current workspace has files that will be removed by rewind.")
        return SafeRewindPreview(
            checkpoint_id=checkpoint_id,
            restore_preview=preview,
            warning_messages=warnings,
        )

    def rewind_workspace(self, checkpoint_id: str) -> dict[str, Any]:
        """执行 workspace 文件恢复。"""
        return self.snapshot_manager.restore_snapshot(checkpoint_id)
