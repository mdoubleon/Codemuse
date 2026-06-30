"""串联 workspace 文件索引、记忆检索和结果格式化流程。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.memory.indexer import WorkspaceIndexReport, build_workspace_file_index
from codemuse.memory.retrieval import RetrievalResult, format_retrieval_hits, retrieve_memory


@dataclass(frozen=True)
class MemoryPipelineReport:
    """记录本地记忆索引刷新后的索引报告和检索可用状态。"""
    index: WorkspaceIndexReport
    retrieval_ready: bool

    def to_dict(self) -> dict[str, Any]:
        """将记忆索引报告转换为可序列化字典。"""
        return {
            "index": self.index.to_dict(),
            "retrieval_ready": self.retrieval_ready,
        }


def refresh_memory_index(workspace: Path, *, max_files: int = 300) -> MemoryPipelineReport:
    """构建或刷新 workspace 的本地确定性文件索引。"""
    report = build_workspace_file_index(workspace, max_files=max_files)
    return MemoryPipelineReport(index=report, retrieval_ready=report.chunk_count > 0)


def search_memory_pipeline(workspace: Path, query: str, *, limit: int = 6) -> RetrievalResult:
    """检索已有记忆和最近一次生成的本地文件索引。"""
    return retrieve_memory(workspace, query, limit=limit)


def format_memory_pipeline_search(result: RetrievalResult) -> str:
    """把记忆检索结果格式化为模型和用户可读文本。"""
    return format_retrieval_hits(result.hits)
