"""保存会话检查点，支持按 checkpoint_id 恢复消息状态。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from codemuse.domain.checkpoints import CheckpointRecord
from codemuse.domain.messages import ChatMessage


class CheckpointStore:
    """基于 JSON 文件的检查点存储。

    每个检查点保存会话消息、turn_id 和 metadata。Runtime 会在此基础上补充工作区快照，
    从而支持手动 rewind 和副作用工具执行前的安全回退。
    """

    def __init__(self, root: Path) -> None:
        """记录存储根目录，后续所有读写都围绕这个目录展开。"""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        session_id: str,
        label: str,
        turn_id: int,
        messages: list[ChatMessage],
        metadata: dict[str, Any] | None = None,
    ) -> CheckpointRecord:
        """创建一条新的领域记录或运行结果。"""
        record = CheckpointRecord(
            checkpoint_id=str(uuid.uuid4()),
            session_id=session_id,
            label=label,
            turn_id=turn_id,
            # 通过 dict 再还原，避免外部继续修改 messages 时影响已经保存的快照。
            messages=[ChatMessage.from_dict(message.to_dict()) for message in messages],
            metadata=metadata or {},
            created_at=time.time(),
        )
        self.save(record)
        return record

    def save(self, record: CheckpointRecord) -> None:
        """将对象写入本地存储。"""
        path = self._path(record.checkpoint_id)
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, checkpoint_id: str) -> CheckpointRecord:
        """按标识读取本地存储中的对象。"""
        path = self._path(checkpoint_id)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")
        return CheckpointRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, *, session_id: str | None = None) -> list[CheckpointRecord]:
        """列出当前存储或目录中的对象。"""
        records: list[CheckpointRecord] = []
        for path in self.root.glob("*.json"):
            record = CheckpointRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if session_id is not None and record.session_id != session_id:
                continue
            records.append(record)
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def _path(self, checkpoint_id: str) -> Path:
        """根据标识计算本地存储路径。"""
        return self.root / f"{checkpoint_id}.json"
