"""定义工具展示、审计和能力目录使用的元数据结构。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolMetadata:
    """保存工具展示、审计和能力目录所需的补充元数据。"""
    name: str
    category: str
    permission_domain: str = "read"
    requires_confirmation: bool = False
    model_callable: bool = True
    side_effect: bool = False

