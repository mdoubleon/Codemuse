"""实现 tools/metadata.py 对应的业务边界和辅助逻辑。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolMetadata:
    """ToolMetadata：封装该领域需要传递的数据和行为。"""
    name: str
    category: str
    permission_domain: str = "read"
    requires_confirmation: bool = False
    model_callable: bool = True
    side_effect: bool = False

