"""实现 Agent 主循环：组装上下文、调用模型、安全执行工具并保存会话。"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codemuse.domain.checkpoints import CheckpointRecord
from codemuse.domain.messages import ChatMessage, TextPart
from codemuse.domain.tools import ToolCall
from codemuse.llm.provider.base import LLMProvider
from codemuse.memory.retrieval_hook import MemoryContextProvider
from codemuse.runtime.events import AgentEvent
from codemuse.runtime.git_checkpoint import WorkspaceSnapshotManager
from codemuse.runtime.safe_rewind import SafeRewindOrchestrator
from codemuse.runtime.state import AgentState
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.storage.checkpoints import CheckpointStore
from codemuse.storage.sessions import SessionRecord, SessionStore
from codemuse.storage.timeline import TimelineStore
from codemuse.tools.effects import build_effect_digest, build_tool_effect_preview, validate_effect_digest, validate_tool_effect_preview
from codemuse.tools.policy import ALLOW, ASK, DENY, ToolPolicyEvaluator
from codemuse.tools.registry import ToolRegistry

Subscriber = Callable[[AgentEvent], None]


class AgentRuntime:
    """控制 Agent ReAct 主循环，负责模型调用、工具调度、审批和状态保存。"""
    def __init__(
        self,
        *,
        workspace: Path,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        session_store: SessionStore,
        session: SessionRecord,
        memory_provider: MemoryContextProvider | None = None,
        approval_store: PendingApprovalStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
        timeline_store: TimelineStore | None = None,
        policy_evaluator: ToolPolicyEvaluator | None = None,
        max_turns: int = 15,
    ) -> None:
        """注入模型、工具注册表、存储和可选记忆/审批/检查点组件，恢复会话状态。"""
        self.workspace = workspace.resolve()
        self.llm = llm
        self.tool_registry = tool_registry
        self.session_store = session_store
        self.memory_provider = memory_provider
        self.approval_store = approval_store
        self.checkpoint_store = checkpoint_store
        self.timeline_store = timeline_store
        self.policy_evaluator = policy_evaluator or ToolPolicyEvaluator()
        self.max_turns = max_turns
        self.state = AgentState(session_id=session.session_id, system_prompt=session.system_prompt, messages=session.messages)
        self._subscribers: list[Subscriber] = []
        self._cancel_event = threading.Event()

    @property
    def session_id(self) -> str:
        """返回当前 Runtime 正在维护的会话 id，供 SDK、CLI 和存储层定位同一轮上下文。"""
        return self.state.session_id

    def subscribe(self, callback: Subscriber) -> None:
        """注册 Runtime 事件订阅回调。"""
        self._subscribers.append(callback)

    def request_cancel(self) -> None:
        """请求中断当前主循环。下一个 turn 边界会退出，不会强杀正在执行的工具。"""
        self._cancel_event.set()

    def is_cancel_requested(self) -> bool:
        """返回当前是否有取消请求挂起。"""
        return self._cancel_event.is_set()

    def prompt(self, text: str) -> list[AgentEvent]:
        """接收用户输入并驱动 Agent 执行一轮任务。"""
        self.state.messages.append(ChatMessage.text("user", text))
        return self._run_loop()

    def create_checkpoint(self, label: str = "manual checkpoint") -> list[AgentEvent]:
        """为当前会话创建一个可回退检查点。"""
        captured: list[AgentEvent] = []
        record = self._create_checkpoint_record(label=label, metadata={"source": "manual"})
        self._emit_checkpoint_created(captured, record)
        return captured

    def rewind(self, checkpoint_id: str) -> list[AgentEvent]:
        """将当前会话恢复到指定检查点。"""
        if self.checkpoint_store is None:
            raise RuntimeError("Checkpoint store is not configured.")
        checkpoint = self.checkpoint_store.load(checkpoint_id)
        if checkpoint.session_id != self.session_id:
            raise ValueError(f"Checkpoint belongs to another session: {checkpoint.session_id}")

        captured: list[AgentEvent] = []
        workspace_restore: dict[str, Any] | None = None
        if checkpoint.metadata.get("workspace_snapshot") and self.checkpoint_store is not None:
            workspace_restore = SafeRewindOrchestrator(self.workspace, self.checkpoint_store.root).rewind_workspace(checkpoint_id)
        self.state.messages = [ChatMessage.from_dict(message.to_dict()) for message in checkpoint.messages]
        self.state.pending_tool_calls = []
        self.state.pending_plan_token = None
        self.state.queued_messages = []
        self.state.memory_context = {}
        self.state.turn_id = checkpoint.turn_id
        self.state.phase = "idle"
        self.state.is_running = False
        self.state.error_message = None
        self._persist()
        self._emit(
            "checkpoint_rewound",
            captured,
            message=f"Rewound to checkpoint: {checkpoint.checkpoint_id}",
            details={
                "checkpoint_id": checkpoint.checkpoint_id,
                "label": checkpoint.label,
                "message_count": len(checkpoint.messages),
                "restored_workspace": bool(workspace_restore),
                "workspace_restore": workspace_restore,
            },
        )
        return captured

    def approve(self, approval_id: str) -> list[AgentEvent]:
        """批准一个等待中的工具调用，并让 Runtime 继续执行。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        approval = self.approval_store.load(approval_id)
        if approval.status != "pending":
            raise ValueError(f"Approval is not pending: {approval_id}")
        if approval.session_id != self.session_id:
            raise ValueError(f"Approval belongs to another session: {approval.session_id}")

        call = ToolCall(id=approval.tool_call_id, name=approval.tool_name, arguments=approval.arguments)
        captured: list[AgentEvent] = []
        digest_validation = validate_effect_digest(approval.tool_name, approval.arguments, approval.details)
        if not digest_validation["ok"]:
            self._mark_invalid_approval(approval_id, call, digest_validation, captured)
            captured.extend(self._run_loop())
            return captured

        validation = validate_tool_effect_preview(
            self.workspace,
            approval.tool_name,
            approval.arguments,
            approval.details.get("effect_preview"),
        )
        if not validation["ok"]:
            self._mark_stale_approval(approval_id, call, validation, captured)
            captured.extend(self._run_loop())
            return captured

        self._emit("approval_approved", captured, tool_name=approval.tool_name, message=f"Approved: {approval_id}")
        # 用户批准后，直接执行原始工具调用；这里不再重复进入审批门。
        self._checkpoint_before_tool(call, captured)
        result = self.tool_registry.execute(approval.tool_name, approval.arguments)
        result.tool_call_id = approval.tool_call_id
        self.state.messages.append(result.as_chat_message())
        self.state.pending_tool_calls = [call for call in self.state.pending_tool_calls if call.id != approval.tool_call_id]
        self.approval_store.mark(approval_id, "approved")
        self._persist()
        self._emit("tool_result", captured, tool_name=approval.tool_name, message=result.content[:500], details=result.details)
        captured.extend(self._run_loop())
        return captured

    def reject(self, approval_id: str) -> list[AgentEvent]:
        """拒绝一个等待中的工具调用，并写回会话。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        approval = self.approval_store.load(approval_id)
        if approval.status != "pending":
            raise ValueError(f"Approval is not pending: {approval_id}")
        if approval.session_id != self.session_id:
            raise ValueError(f"Approval belongs to another session: {approval.session_id}")

        captured: list[AgentEvent] = []
        self.approval_store.mark(approval_id, "rejected")
        # 拒绝也要写回 tool 消息，让模型知道这次工具调用没有被执行。
        self.state.messages.append(
            ChatMessage(
                role="tool",
                tool_call_id=approval.tool_call_id,
                tool_name=approval.tool_name,
                content=[TextPart(text=f"Approval rejected for {approval.tool_name}: {approval.reason}")],
                metadata={"success": False, "is_error": True, "approval_id": approval_id},
            )
        )
        self.state.pending_tool_calls = [call for call in self.state.pending_tool_calls if call.id != approval.tool_call_id]
        self._persist()
        self._emit("approval_rejected", captured, tool_name=approval.tool_name, message=f"Rejected: {approval_id}", is_error=True)
        captured.extend(self._run_loop())
        return captured

    def _run_loop(self) -> list[AgentEvent]:
        """执行 ReAct 主循环：调用模型、处理工具调用、审批暂停和最终收尾。"""
        captured: list[AgentEvent] = []
        self._cancel_event.clear()
        self.state.is_running = True
        self._emit("agent_start", captured, message="Agent started.")
        keep_running = True
        turns = 0
        cancelled = False
        try:
            while keep_running and turns < self.max_turns:
                if self._cancel_event.is_set():
                    cancelled = True
                    break
                turns += 1
                self.state.turn_id += 1
                self.state.phase = "planning"
                self._emit("turn_start", captured, details={"turn_id": self.state.turn_id})
                response = self.llm.complete(self._messages_for_model(), self.tool_registry.specs())
                if response.text:
                    self.state.messages.append(ChatMessage.text("assistant", response.text))
                    self._emit("message", captured, message=response.text)
                if response.tool_calls:
                    assistant_message = ChatMessage(role="assistant", tool_calls=response.tool_calls)
                    self.state.messages.append(assistant_message)
                    self.state.phase = "executing"
                    stopped_for_approval = False
                    for call in response.tool_calls:
                        if self._cancel_event.is_set():
                            cancelled = True
                            break
                        self._emit("tool_call", captured, tool_name=call.name, details={"arguments": call.arguments})
                        decision = self._policy_decision(call)
                        if decision.action == DENY:
                            self._append_tool_error(call, decision.reason)
                            self._emit("tool_error", captured, tool_name=call.name, message=decision.reason, details=decision.details, is_error=True)
                            continue
                        if decision.action == ASK:
                            approval = self._stage_approval(call, decision.reason)
                            self.state.pending_tool_calls.append(call)
                            self.state.phase = "awaiting_approval"
                            stopped_for_approval = True
                            approval_details = {
                                "approval_id": approval.approval_id,
                                "reason": approval.reason,
                                "arguments": call.arguments,
                            }
                            approval_details.update(approval.details)
                            self._emit(
                                "approval_required",
                                captured,
                                tool_name=call.name,
                                message=f"Approval required for {call.name}. approval_id={approval.approval_id}",
                                details=approval_details,
                            )
                            break
                        try:
                            self._checkpoint_before_tool(call, captured)
                            result = self.tool_registry.execute(call.name, call.arguments)
                            result.tool_call_id = call.id
                            self.state.messages.append(result.as_chat_message())
                            self._emit("tool_result", captured, tool_name=call.name, message=result.content[:500], details=result.details)
                        except Exception as exc:  # noqa: BLE001 - phase 1 records tool failures as observations
                            error_text = str(exc)
                            self._append_tool_error(call, error_text)
                            self._emit("tool_error", captured, tool_name=call.name, message=error_text, is_error=True)
                    if cancelled:
                        break
                    if stopped_for_approval:
                        keep_running = False
                        self._emit("turn_end", captured, details={"turn_id": self.state.turn_id, "phase": "awaiting_approval"})
                        continue
                    keep_running = True
                    continue
                keep_running = False
                self._emit("turn_end", captured, details={"turn_id": self.state.turn_id})
        finally:
            if cancelled:
                self.state.phase = "cancelled"
                self._emit(
                    "agent_cancelled",
                    captured,
                    message="Agent cancelled by user request.",
                    details={"turn_id": self.state.turn_id},
                )
            else:
                self.state.phase = "idle"
            self.state.is_running = False
            self._cancel_event.clear()
            self._persist()
            self._emit("agent_end", captured, message="Agent ended.")
        return captured

    def _messages_for_model(self) -> list[ChatMessage]:
        """构造发给模型的上下文，并在调用前注入相关长期记忆。"""
        messages = [ChatMessage.text("system", self.state.system_prompt)]
        messages.extend(self.state.messages[-20:])
        if self.memory_provider is not None:
            messages = self.memory_provider.transform_context(self.state, messages)
        return messages

    def _policy_decision(self, call: ToolCall):
        """读取工具规格，并根据权限域和副作用计算安全策略。"""
        spec = self.tool_registry.get_spec(call.name)
        return self.policy_evaluator.evaluate(spec)

    def _stage_approval(self, call: ToolCall, reason: str):
        """创建审批单，并在审批单里保存执行前影响预览。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        details: dict[str, Any] = {}
        effect_preview = build_tool_effect_preview(self.workspace, call.name, call.arguments)
        if effect_preview is not None:
            details["effect_preview"] = effect_preview
        details["effect_digest"] = build_effect_digest(call.name, call.arguments, details.get("effect_preview"))
        return self.approval_store.create(session_id=self.session_id, call=call, reason=reason, details=details)

    def _mark_invalid_approval(
        self,
        approval_id: str,
        call: ToolCall,
        validation: dict[str, Any],
        captured: list[AgentEvent],
    ) -> None:
        """把摘要不匹配的审批标记为 invalid，阻止被篡改的工具调用继续执行。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        reason = str(validation.get("reason") or "Approval digest is invalid.")
        invalid_details = {
            "invalid_reason": reason,
            "invalid_stored_digest": validation.get("stored_digest") or "",
            "invalid_expected_digest": validation.get("expected_digest") or "",
        }
        self.approval_store.mark(approval_id, "invalid", details_update=invalid_details)
        self.state.pending_tool_calls = [item for item in self.state.pending_tool_calls if item.id != call.id]
        self.state.messages.append(
            ChatMessage(
                role="tool",
                tool_call_id=call.id,
                tool_name=call.name,
                content=[TextPart(text=f"Approval invalid for {call.name}: {reason}")],
                metadata={"success": False, "is_error": True, "approval_id": approval_id, "invalid": True},
            )
        )
        self._persist()
        self._emit(
            "approval_invalid",
            captured,
            tool_name=call.name,
            message=f"Approval invalid: {approval_id}",
            details=invalid_details | {"approval_id": approval_id},
            is_error=True,
        )

    def _mark_stale_approval(
        self,
        approval_id: str,
        call: ToolCall,
        validation: dict[str, Any],
        captured: list[AgentEvent],
    ) -> None:
        """把过期审批标记为 stale，阻止工具按旧 diff 修改当前文件。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        reason = str(validation.get("reason") or "Approval preview is stale.")
        stale_details = {
            "stale_reason": reason,
            "stale_changed_fields": validation.get("changed_fields") or [],
            "stale_current_preview": validation.get("current_preview"),
        }
        self.approval_store.mark(approval_id, "stale", details_update=stale_details)
        self.state.pending_tool_calls = [item for item in self.state.pending_tool_calls if item.id != call.id]
        self.state.messages.append(
            ChatMessage(
                role="tool",
                tool_call_id=call.id,
                tool_name=call.name,
                content=[TextPart(text=f"Approval stale for {call.name}: {reason}")],
                metadata={"success": False, "is_error": True, "approval_id": approval_id, "stale": True},
            )
        )
        self._persist()
        self._emit(
            "approval_stale",
            captured,
            tool_name=call.name,
            message=f"Approval stale: {approval_id}",
            details={
                "approval_id": approval_id,
                "reason": reason,
                "changed_fields": validation.get("changed_fields") or [],
                "current_preview": validation.get("current_preview"),
            },
            is_error=True,
        )

    def _checkpoint_before_tool(self, call: ToolCall, captured: list[AgentEvent]) -> CheckpointRecord | None:
        """副作用工具执行前创建检查点，方便后续 rewind。"""
        if self.checkpoint_store is None:
            return None
        spec = self.tool_registry.get_spec(call.name)
        needs_checkpoint = spec.side_effect or spec.permission_domain in {"write", "shell", "network", "external"}
        if not needs_checkpoint:
            return None
        record = self._create_checkpoint_record(
            label=f"before tool {call.name}",
            metadata={
                "source": "tool",
                "tool_name": call.name,
                "tool_call_id": call.id,
                "permission_domain": spec.permission_domain,
                "side_effect": spec.side_effect,
            },
        )
        self._emit_checkpoint_created(captured, record, tool_name=call.name)
        return record

    def _create_checkpoint_record(self, *, label: str, metadata: dict[str, Any]) -> CheckpointRecord:
        """保存会话检查点，并附加当前工作区文件快照。"""
        if self.checkpoint_store is None:
            raise RuntimeError("Checkpoint store is not configured.")
        record = self.checkpoint_store.create(
            session_id=self.session_id,
            label=label,
            turn_id=self.state.turn_id,
            messages=self.state.messages,
            metadata=metadata,
        )
        snapshot = WorkspaceSnapshotManager(self.workspace, self.checkpoint_store.root).create_snapshot(record.checkpoint_id)
        record.metadata["workspace_snapshot"] = snapshot
        self.checkpoint_store.save(record)
        return record

    def _emit_checkpoint_created(
        self,
        captured: list[AgentEvent],
        record: CheckpointRecord,
        *,
        tool_name: str | None = None,
    ) -> None:
        """创建并发布 Runtime 事件。"""
        self._emit(
            "checkpoint_created",
            captured,
            tool_name=tool_name,
            message=f"Checkpoint created: {record.checkpoint_id}",
            details={
                "checkpoint_id": record.checkpoint_id,
                "label": record.label,
                "message_count": len(record.messages),
                "workspace_snapshot": record.metadata.get("workspace_snapshot"),
            },
        )

    def _append_tool_error(self, call: ToolCall, error_text: str) -> None:
        """把工具错误写成 role=tool 的消息，供模型下一轮读取。"""
        self.state.messages.append(
            ChatMessage(
                role="tool",
                tool_call_id=call.id,
                tool_name=call.name,
                content=[TextPart(text=error_text)],
                metadata={"success": False, "is_error": True, "error": error_text},
            )
        )

    def _persist(self) -> None:
        """把当前会话的系统提示和消息历史写入 SessionStore。"""
        record = SessionRecord(
            session_id=self.state.session_id,
            system_prompt=self.state.system_prompt,
            messages=self.state.messages,
        )
        self.session_store.save(record)

    def _emit(
        self,
        event_type: str,
        captured: list[AgentEvent],
        *,
        message: str | None = None,
        tool_name: str | None = None,
        details: dict[str, Any] | None = None,
        is_error: bool = False,
    ) -> None:
        """创建并发布 Runtime 事件。"""
        event = AgentEvent(
            type=event_type,
            session_id=self.state.session_id,
            turn_id=self.state.turn_id,
            phase=self.state.phase,
            message=message,
            tool_name=tool_name,
            details=details or {},
            is_error=is_error,
        )
        captured.append(event)
        if self.timeline_store is not None:
            self.timeline_store.append(event)
        for subscriber in self._subscribers:
            subscriber(event)
