"""在模型调用前检索蓝图记忆和项目记忆，并注入上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codemuse.domain.messages import ChatMessage, TextPart
from codemuse.memory.retrieval import format_retrieval_hits, retrieve_memory

MEMORY_RECALL_METADATA_KEY = "memory_recall"


@dataclass
class MemoryContextProvider:
    """在 Runtime 调模型前检索记忆，并把命中内容插入 messages。"""
    workspace: Path
    enabled: bool = True
    limit: int = 3
    max_chars: int = 1800

    def transform_context(self, state: Any, messages: list[ChatMessage]) -> list[ChatMessage]:
        """在模型调用前改写或增强消息上下文。"""
        if not self.enabled:
            return messages
        query = self._latest_user_text(messages)
        if not query:
            return messages
        result = retrieve_memory(self.workspace, query, limit=self.limit)
        if not result.hits:
            return messages
        snippet = format_retrieval_hits(result.hits)
        if len(snippet) > self.max_chars:
            snippet = snippet[: self.max_chars].rstrip() + "\n...[memory truncated]"
        metadata = {
            "source": "hybrid_memory",
            "query": query,
            "distribution": result.distribution,
            "hits": [hit.to_dict() for hit in result.hits],
        }
        if state is not None:
            state.memory_context[MEMORY_RECALL_METADATA_KEY] = metadata
        recall_message = ChatMessage(
            role="system",
            content=[
                TextPart(
                    text=(
                        "Relevant CodeMuse memory was recalled for this turn.\n"
                        "Use it as background context, but prefer current workspace evidence when there is a conflict.\n\n"
                        f"{snippet}"
                    )
                )
            ],
            metadata={MEMORY_RECALL_METADATA_KEY: metadata},
        )
        insert_at = self._insertion_index(messages)
        return [*messages[:insert_at], recall_message, *messages[insert_at:]]

    @staticmethod
    def _latest_user_text(messages: list[ChatMessage]) -> str:
        """从消息列表末尾找到最新用户输入，作为记忆检索 query。"""
        for message in reversed(messages):
            if message.role == "user":
                return message.text_content().strip()
        return ""

    @staticmethod
    def _insertion_index(messages: list[ChatMessage]) -> int:
        """把召回消息插到初始 system prompt 之后、用户消息之前。"""
        index = 0
        while index < len(messages) and messages[index].role == "system":
            index += 1
        return index
