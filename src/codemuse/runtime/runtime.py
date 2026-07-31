"""实现 Agent 主循环：组装上下文、调用模型、安全执行工具并保存会话。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codemuse.domain.checkpoints import CheckpointRecord
from codemuse.domain.messages import ChatMessage, TextPart
from codemuse.domain.tools import ToolCall
from codemuse.llm.provider.base import LLMProvider, iter_provider_stream
from codemuse.llm.models import LLMResponse
from codemuse.memory.retrieval_hook import MemoryContextProvider
from codemuse.runtime.events import AgentEvent
from codemuse.runtime.compaction import ConversationCompactor
from codemuse.runtime.cancellation import CancellationToken
from codemuse.runtime.emitter import LifecycleEmitter
from codemuse.runtime.executor import ApprovalValidationError, Executor, ToolExecutionError
from codemuse.runtime.hooks import RuntimeHooks
from codemuse.runtime.planner import Plan, PlannedToolCall, Planner
from codemuse.runtime.turn_loop import TurnController
from codemuse.runtime.git_checkpoint import WorkspaceSnapshotManager
from codemuse.runtime.safe_rewind import SafeRewindOrchestrator
from codemuse.runtime.state import AgentState
from codemuse.storage.approvals import PendingApproval, PendingApprovalStore
from codemuse.storage.checkpoints import CheckpointStore
from codemuse.storage.sessions import SessionRecord, SessionStore
from codemuse.storage.timeline import TimelineStore
from codemuse.tools.policy import ToolPolicyEvaluator
from codemuse.tools.registry import ToolRegistry

Subscriber = Callable[[AgentEvent], None]

_TOOL_LIMIT_FINAL_SUMMARY_INSTRUCTION = (
    "The tool-use limit for this task has been reached. Based only on the "
    "conversation and tool results already available, provide the best final "
    "answer to the user now. Do not request, call, or suggest any additional "
    "tools. If the available results are insufficient, state the limitation "
    "clearly and explain what remains unknown."
)
_TOOL_LIMIT_FINAL_FALLBACK = (
    "The tool-use limit has been reached, so I cannot run more tools. "
    "I can only answer from the results already available."
)
_TOOLS_DISABLED_INSTRUCTION = (
    "Tools are disabled for this chat. Answer directly from the conversation "
    "and any results already available. Do not request, call, or suggest tools."
)
_TOOLS_DISABLED_FALLBACK = (
    "Tools are disabled for this chat, so I did not execute the requested tool calls. "
    "Enable tools to perform workspace, shell, web, or other tool actions."
)


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
        max_tool_calls_per_turn: int = 4,
        max_tool_calls_per_prompt: int = 8,
        history_token_budget: int = 16000,
        tools_enabled: bool = True,
        hooks: RuntimeHooks | None = None,
        emitter: LifecycleEmitter | None = None,
        turn_controller: TurnController | None = None,
        compactor: ConversationCompactor | None = None,
        cancellation_token: CancellationToken | None = None,
        planner: Planner | None = None,
        executor: Executor | None = None,
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
        if isinstance(max_tool_calls_per_turn, bool) or not isinstance(max_tool_calls_per_turn, int):
            raise ValueError("max_tool_calls_per_turn must be an integer.")
        if max_tool_calls_per_turn < 1:
            raise ValueError("max_tool_calls_per_turn must be at least 1.")
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        if isinstance(max_tool_calls_per_prompt, bool) or not isinstance(max_tool_calls_per_prompt, int):
            raise ValueError("max_tool_calls_per_prompt must be an integer.")
        if max_tool_calls_per_prompt < 1:
            raise ValueError("max_tool_calls_per_prompt must be at least 1.")
        self.max_tool_calls_per_prompt = max_tool_calls_per_prompt
        self.history_token_budget = history_token_budget
        if not isinstance(tools_enabled, bool):
            raise ValueError("tools_enabled must be a boolean.")
        self.tools_enabled = tools_enabled
        self.emitter = emitter or LifecycleEmitter()
        self.hooks = hooks or RuntimeHooks()
        self.turn_controller = turn_controller or TurnController()
        self.compactor = compactor or ConversationCompactor(threshold_tokens=max(256, int(history_token_budget * 1.25)))
        self.hooks.register_with_lifecycle(self.emitter)
        self.session = session
        self.state = AgentState(session_id=session.session_id, system_prompt=session.system_prompt, messages=session.messages, queued_messages=list(session.queued_messages))
        self._subscribers: list[Subscriber] = []
        self._cancel_event = threading.Event()
        self._owns_cancellation_token = cancellation_token is None
        self.cancellation_token = cancellation_token or CancellationToken()
        self.planner = planner or Planner(
            workspace=self.workspace,
            tool_registry=self.tool_registry,
            policy_evaluator=self.policy_evaluator,
        )
        self.executor = executor or Executor(
            workspace=self.workspace,
            tool_registry=self.tool_registry,
            approval_store=self.approval_store,
            policy_evaluator=self.policy_evaluator,
        )
        self.last_plan: Plan | None = None
        self._active_turn_node_id: str | None = None
        self._prompt_tool_calls_used = 0
        self._prompt_tool_budget_active = False
        self._restore_pending_tool_calls()

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
        self.cancellation_token.cancel()

    def is_cancel_requested(self) -> bool:
        """返回当前是否有取消请求挂起。"""
        return self._cancel_event.is_set() or self.cancellation_token.is_cancelled

    def enqueue_message(self, text: str, *, delivery: str = "follow_up") -> None:
        """Queue steering/follow-up input for the next available turn."""
        clean = text.strip()
        if not clean:
            raise ValueError("Queued message cannot be empty.")
        from codemuse.runtime.state import QueuedMessage
        self.state.queued_messages.append(QueuedMessage(clean, delivery=delivery))
        self._emit("queue_enqueued", [], message=clean, details={"delivery": delivery, "queue_size": len(self.state.queued_messages)})
        self._persist()

    def compact(self) -> dict[str, Any]:
        """Compact persisted history and return a small operation report."""
        captured: list[AgentEvent] = []
        before = len(self.state.messages)
        self._emit("session_before_compact", captured, details={"message_count": before})
        decision = self.emitter.emit_session_before_compact(captured[-1]) if captured else None
        if decision is not None and not decision.allow:
            return {"compacted": False, "removed_messages": 0, "message_count": before, "reason": "blocked_by_hook"}
        result = self.compactor.compact(self.state.messages, self._estimate_messages_tokens)
        if result.compacted:
            self.state.messages = result.messages
            self._persist()
            self._emit("session_compacted", captured, message=result.summary[:500], details=result.to_dict())
        return {**result.to_dict(), "message_count": len(self.state.messages)}

    def prompt(self, text: str) -> list[AgentEvent]:
        """接收用户输入并驱动 Agent 执行一轮任务。"""
        if self._restore_pending_tool_calls():
            raise RuntimeError("Cannot start a new prompt while this session has unresolved approvals.")
        self._prompt_tool_calls_used = 0
        self._prompt_tool_budget_active = True
        self.state.messages.append(ChatMessage.text("user", text))
        if self.compactor.should_compact(self.state.messages, self._estimate_messages_tokens):
            self.compact()
        return self._run_loop()

    def create_checkpoint(self, label: str = "manual checkpoint") -> list[AgentEvent]:
        """为当前会话创建一个可回退检查点。"""
        captured: list[AgentEvent] = []
        record = self._create_checkpoint_record(label=label, metadata={"source": "manual"})
        self._emit_checkpoint_created(captured, record)
        return captured

    def preview_rewind(self, checkpoint_id: str, *, mode: str = "conversation_and_workspace") -> dict[str, Any]:
        """Preview a rewind without changing conversation or workspace state."""
        if self.checkpoint_store is None:
            raise RuntimeError("Checkpoint store is not configured.")
        checkpoint = self.checkpoint_store.load(checkpoint_id)
        if checkpoint.session_id != self.session_id:
            raise ValueError(f"Checkpoint belongs to another session: {checkpoint.session_id}")
        preview = SafeRewindOrchestrator(self.workspace, self.checkpoint_store.root).preview_rewind(checkpoint_id, mode=mode)
        return {
            "checkpoint_id": checkpoint_id,
            "mode": mode,
            "label": checkpoint.label,
            "target_message_count": len(checkpoint.messages),
            "target_turn_id": checkpoint.turn_id,
            "restore_preview": preview.restore_preview,
            "warning_messages": preview.warning_messages,
        }

    def rewind(self, checkpoint_id: str, *, mode: str = "conversation_and_workspace") -> list[AgentEvent]:
        """将当前会话恢复到指定检查点。"""
        if self.checkpoint_store is None:
            raise RuntimeError("Checkpoint store is not configured.")
        checkpoint = self.checkpoint_store.load(checkpoint_id)
        if checkpoint.session_id != self.session_id:
            raise ValueError(f"Checkpoint belongs to another session: {checkpoint.session_id}")
        if mode not in {"conversation_only", "workspace_only", "conversation_and_workspace"}:
            raise ValueError(f"Unsupported rewind mode: {mode}")

        captured: list[AgentEvent] = []
        workspace_restore: dict[str, Any] | None = None
        restore_workspace = mode in {"workspace_only", "conversation_and_workspace"}
        restore_conversation = mode in {"conversation_only", "conversation_and_workspace"}
        rewind_preview = SafeRewindOrchestrator(self.workspace, self.checkpoint_store.root).preview_rewind(
            checkpoint_id,
            mode=mode,
        )
        approval_reconciliation = {"invalidated": [], "retained": [], "blockers": []}
        if restore_conversation:
            approval_reconciliation = self._reconcile_approvals_for_rewind(checkpoint)
            if approval_reconciliation["blockers"]:
                blockers = ", ".join(approval_reconciliation["blockers"])
                raise RuntimeError(
                    "Cannot rewind while later approval execution is unresolved: "
                    f"{blockers}"
                )
        if restore_workspace and checkpoint.metadata.get("workspace_snapshot") and self.checkpoint_store is not None:
            workspace_restore = SafeRewindOrchestrator(self.workspace, self.checkpoint_store.root).rewind_workspace(checkpoint_id)
        if restore_conversation:
            self.state.messages = [ChatMessage.from_dict(message.to_dict()) for message in checkpoint.messages]
            self.state.pending_tool_calls = []
            self.state.pending_plan_token = None
            self.state.queued_messages = []
            self.state.memory_context = {}
            self.state.turn_id = checkpoint.turn_id
            self.state.phase = "idle"
            self.state.is_running = False
            self.state.error_message = None
            checkpoint_head_id = str(checkpoint.metadata.get("head_id") or "")
            if checkpoint_head_id and any(
                str(node.get("turn_node_id") or "") == checkpoint_head_id
                for node in self.session.turns
            ):
                self.session.active_head_id = checkpoint_head_id
            self._active_turn_node_id = None
            self._restore_pending_tool_calls()
            self._persist()
        self._emit(
            "checkpoint_rewound",
            captured,
            message=f"Rewound to checkpoint: {checkpoint.checkpoint_id}",
            details={
                "checkpoint_id": checkpoint.checkpoint_id,
                "label": checkpoint.label,
                "mode": mode,
                "message_count": len(checkpoint.messages),
                "restored_conversation": restore_conversation,
                "restored_workspace": bool(workspace_restore),
                "workspace_restore": workspace_restore,
                "risk_preview": rewind_preview.restore_preview,
                "warning_messages": rewind_preview.warning_messages,
                "invalidated_approval_ids": approval_reconciliation["invalidated"],
                "retained_approval_ids": approval_reconciliation["retained"],
            },
        )
        return captured

    def approve(self, approval_id: str) -> list[AgentEvent]:
        """批准一个等待中的工具调用，并让 Runtime 继续执行。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        approval = self.approval_store.load(approval_id)
        if approval.session_id != self.session_id:
            raise ValueError(f"Approval belongs to another session: {approval.session_id}")

        # A pending effect is part of the turn head that staged it.  Do not let a
        # sibling branch consume it just because both branches share a session id.
        # Stale/invalid approvals still go through the Executor so callers receive
        # the persisted terminal reason rather than a misleading head error.
        if approval.status == "pending" or (
            approval.status == "approved" and approval.execution_status == "completed"
        ):
            self._require_approval_on_active_head(approval)

        call = ToolCall(id=approval.tool_call_id, name=approval.tool_name, arguments=approval.arguments)
        captured: list[AgentEvent] = []
        if not self.tools_enabled and approval.status == "pending":
            return self._block_approved_tool_when_disabled(approval_id, call, captured)
        if approval.status == "pending":
            self._require_no_unresolved_session_execution()

        def before_execute(executing_call: ToolCall, execution_id: str) -> None:
            self._emit(
                "approval_approved",
                captured,
                tool_name=executing_call.name,
                message=f"Approved: {approval_id}",
                details={"approval_id": approval_id, "execution_id": execution_id},
            )
            self.state.phase = "executing"
            self._emit(
                "tool_call",
                captured,
                tool_name=executing_call.name,
                details={
                    "arguments": executing_call.arguments,
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                },
            )
            self._checkpoint_before_tool(executing_call, captured)

        def transform_result(executing_call: ToolCall, result):
            result_decision = self.emitter.emit_tool_result(captured[-1], self.state, executing_call, result)
            return result_decision.result if result_decision.result is not None else result

        try:
            outcome = self.executor.execute_approved(
                approval_id,
                session_id=self.session_id,
                before_execute=before_execute,
                transform_result=transform_result,
            )
        except ApprovalValidationError as exc:
            if exc.status == "invalid":
                self._mark_invalid_approval(approval_id, call, exc.validation, captured)
            else:
                self._mark_stale_approval(approval_id, call, exc.validation, captured)
            return self._continue_after_approval_resolution(captured)
        except ToolExecutionError as exc:
            self._record_approved_execution_failure(approval_id, exc, captured)
            return self._continue_after_approval_resolution(captured)

        already_recorded = any(
            message.role == "tool" and message.tool_call_id == outcome.call.id
            for message in self.state.messages
        )
        if not already_recorded:
            self.state.messages.append(outcome.result.as_chat_message())
        self.state.pending_tool_calls = [item for item in self.state.pending_tool_calls if item.id != outcome.call.id]
        self._persist()
        if outcome.replayed:
            self._emit(
                "approval_replayed",
                captured,
                tool_name=outcome.call.name,
                message=f"Approval was already completed: {approval_id}",
                details={"approval_id": approval_id, "execution_id": outcome.execution_id},
            )
            # A repeated API request must not advance the model twice. Recovery from a
            # crash after durable completion may still need to append the missing result.
            return self._continue_after_approval_resolution(captured) if not already_recorded else captured
        self._emit(
            "approval_completed",
            captured,
            tool_name=outcome.call.name,
            message=f"Approval execution completed: {approval_id}",
            details={"approval_id": approval_id, "execution_id": outcome.execution_id},
        )
        self._emit(
            "tool_result",
            captured,
            tool_name=outcome.call.name,
            message=outcome.result.content[:500],
            details={**outcome.result.details, "approval_id": approval_id, "execution_id": outcome.execution_id},
        )
        return self._continue_after_approval_resolution(captured)

    def reject(self, approval_id: str) -> list[AgentEvent]:
        """拒绝一个等待中的工具调用，并写回会话。"""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        approval = self.approval_store.load(approval_id)
        if approval.status != "pending":
            raise ValueError(f"Approval is not pending: {approval_id}")
        if approval.session_id != self.session_id:
            raise ValueError(f"Approval belongs to another session: {approval.session_id}")
        self._require_approval_on_active_head(approval)

        captured: list[AgentEvent] = []
        self.approval_store.mark(approval_id, "rejected")
        if approval.tool_name == "apply_patch_artifact":
            from codemuse.subagents.worktree import WorktreeManager
            artifact_manager = WorktreeManager(self.workspace)
            artifact = artifact_manager.load_artifact(str(approval.arguments.get("artifact_id") or ""))
            artifact_manager.update_status(artifact, "rejected")
            artifact_manager.cleanup(artifact)
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
        return self._continue_after_approval_resolution(captured)

    def _block_approved_tool_when_disabled(
        self,
        approval_id: str,
        call: ToolCall,
        captured: list[AgentEvent],
    ) -> list[AgentEvent]:
        """Reject a previously staged tool call when this chat has since disabled tools."""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        message = f"Tool execution is disabled for this chat; {call.name} was not run."
        self.approval_store.mark(approval_id, "rejected", details_update={"blocked_reason": "tools_disabled"})
        self._append_tool_error(call, message)
        self.state.pending_tool_calls = [item for item in self.state.pending_tool_calls if item.id != call.id]
        self._persist()
        self._emit(
            "tool_error",
            captured,
            tool_name=call.name,
            message=message,
            details={"reason": "tools_disabled", "approval_id": approval_id},
            is_error=True,
        )
        self._emit(
            "approval_rejected",
            captured,
            tool_name=call.name,
            message=f"Rejected because tools are disabled: {approval_id}",
            details={"reason": "tools_disabled", "approval_id": approval_id},
            is_error=True,
        )
        return self._continue_after_approval_resolution(captured)

    def _run_loop(self) -> list[AgentEvent]:
        """执行 ReAct 主循环：调用模型、处理工具调用、审批暂停和最终收尾。"""
        captured: list[AgentEvent] = []
        self._cancel_event.clear()
        if self._owns_cancellation_token:
            self.cancellation_token.reset()
        self.state.is_running = True
        self._emit("agent_start", captured, message="Agent started.")
        keep_running = True
        tool_turns = 0
        if not self._prompt_tool_budget_active:
            self._prompt_tool_budget_active = True
            self._prompt_tool_calls_used = 0
        tool_calls_used = self._prompt_tool_calls_used
        cancelled = False
        try:
            while keep_running:
                if self.is_cancel_requested():
                    cancelled = True
                    break
                if tool_turns >= self.max_turns or (
                    self.tools_enabled and tool_calls_used >= self.max_tool_calls_per_prompt
                ):
                    self._run_tool_limit_final_summary(captured)
                    break
                if self.state.queued_messages:
                    queued = self.state.queued_messages.pop(0)
                    self.state.messages.append(ChatMessage.text("user", queued.text))
                    self._emit("queue_dequeued", captured, message=queued.text, details={"delivery": queued.delivery, "queue_size": len(self.state.queued_messages)})
                self.state.turn_id += 1
                self._begin_turn_node()
                turn_start = self.turn_controller.on_turn_start(self.state)
                self.state.phase = turn_start.phase or "planning"
                self._emit("turn_start", captured, details={"turn_id": self.state.turn_id})
                model_messages = self._messages_for_model()
                available_tools = self.tool_registry.specs() if self.tools_enabled else []
                request_event = AgentEvent(type="before_provider_request", session_id=self.session_id, turn_id=self.state.turn_id, phase=self.state.phase)
                request = self.emitter.emit_before_provider_request(request_event, self.state, model_messages, available_tools)
                request_messages = list(request.messages if request.messages is not None else model_messages)
                if not self.tools_enabled:
                    request_messages.append(ChatMessage.text("system", _TOOLS_DISABLED_INSTRUCTION))
                # A disabled chat never sends tools, even if a lifecycle hook tries to add them.
                request_tools = (request.tools if request.tools is not None else available_tools) if self.tools_enabled else []
                self._emit(
                    "before_provider_request",
                    captured,
                    details={"message_count": len(request_messages), "tool_count": len(request_tools), "tools_enabled": self.tools_enabled},
                )
                response = self._collect_provider_response(request_messages, request_tools, captured)
                response_event = AgentEvent(type="provider_response", session_id=self.session_id, turn_id=self.state.turn_id, phase=self.state.phase)
                response_decision = self.emitter.emit_provider_response(response_event, response.text, response.tool_calls)
                if response_decision.assistant_text is not None:
                    response.text = response_decision.assistant_text
                if response_decision.tool_calls is not None:
                    response.tool_calls = response_decision.tool_calls
                if self.tools_enabled:
                    response.tool_calls = self._limit_response_tool_calls(
                        response.tool_calls,
                        captured,
                        prompt_tool_calls_used=tool_calls_used,
                    )
                    tool_calls_used += len(response.tool_calls)
                    self._prompt_tool_calls_used = tool_calls_used
                if response.text:
                    self.state.messages.append(ChatMessage.text("assistant", response.text))
                    self._emit("message", captured, message=response.text)
                if response.tool_calls:
                    if not self.tools_enabled:
                        self._record_disabled_tool_calls(response.tool_calls, captured)
                        keep_running = False
                        self._emit("turn_end", captured, details={"turn_id": self.state.turn_id, "tools_enabled": False})
                        continue
                    plan = self.planner.create_plan(
                        session_id=self.session_id,
                        turn_id=self.state.turn_id,
                        tool_calls=response.tool_calls,
                        assistant_text=response.text,
                    )
                    self.last_plan = plan
                    self.state.pending_plan_token = plan.plan_id
                    self._emit(
                        "plan_created",
                        captured,
                        details={
                            "plan_id": plan.plan_id,
                            "tool_call_count": len(plan.tool_calls),
                            "approval_count": sum(1 for item in plan.tool_calls if item.requires_approval),
                            "denied_count": sum(1 for item in plan.tool_calls if not item.executable),
                        },
                    )
                    assistant_message = ChatMessage(role="assistant", tool_calls=[item.call for item in plan.tool_calls])
                    self.state.messages.append(assistant_message)
                    self.state.phase = "executing"
                    stopped_for_approval = False
                    tool_failed = False
                    for planned in plan.tool_calls:
                        call = planned.call
                        if self.is_cancel_requested():
                            cancelled = True
                            break
                        self._emit(
                            "tool_call",
                            captured,
                            tool_name=call.name,
                            details={
                                "arguments": call.arguments,
                                "plan_id": plan.plan_id,
                                "planned_action": planned.action,
                            },
                        )
                        hook_decision = self.emitter.emit_tool_call(captured[-1], self.state, call, self.tool_registry)
                        if hook_decision.action == "deny":
                            tool_failed = True
                            self._append_tool_error(call, hook_decision.message or "Tool call blocked by runtime hook.")
                            self._emit("tool_error", captured, tool_name=call.name, message=hook_decision.message or "Tool call blocked by runtime hook.", is_error=True)
                            continue
                        if not planned.executable:
                            tool_failed = True
                            self._append_tool_error(call, planned.reason)
                            self._emit(
                                "tool_error",
                                captured,
                                tool_name=call.name,
                                message=planned.reason,
                                details={**planned.details, "plan_id": plan.plan_id},
                                is_error=True,
                            )
                            continue
                        if planned.requires_approval:
                            self.state.phase = self.turn_controller.before_plan_approval().phase
                            approval = self._stage_approval(planned, plan_id=plan.plan_id)
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
                            continue

                        def before_execute(executing_call: ToolCall, _execution_id: str) -> None:
                            self._checkpoint_before_tool(executing_call, captured)

                        def transform_result(executing_call: ToolCall, result):
                            result_decision = self.emitter.emit_tool_result(captured[-1], self.state, executing_call, result)
                            return result_decision.result if result_decision.result is not None else result

                        try:
                            outcome = self.executor.execute(
                                planned,
                                before_execute=before_execute,
                                transform_result=transform_result,
                            )
                            self.state.messages.append(outcome.result.as_chat_message())
                            self._emit(
                                "tool_result",
                                captured,
                                tool_name=call.name,
                                message=outcome.result.content[:500],
                                details={**outcome.result.details, "execution_id": outcome.execution_id, "plan_id": plan.plan_id},
                            )
                        except ToolExecutionError as exc:
                            tool_failed = True
                            error_text = str(exc)
                            self.emitter.emit_tool_error(captured[-1], self.state, call, exc.cause)
                            self._append_tool_error(call, error_text)
                            self._emit(
                                "tool_error",
                                captured,
                                tool_name=call.name,
                                message=error_text,
                                details={"execution_id": exc.execution_id, "plan_id": plan.plan_id},
                                is_error=True,
                            )
                    if cancelled:
                        break
                    if stopped_for_approval:
                        keep_running = False
                        self._emit("turn_end", captured, details={"turn_id": self.state.turn_id, "phase": "awaiting_approval"})
                        continue
                    self.state.pending_plan_token = None
                    tool_turns += 1
                    next_message = self.state.queued_messages[0] if self.state.queued_messages else None
                    round_decision = self.turn_controller.after_tool_round(
                        tool_failed=tool_failed,
                        continue_after_error=True,
                        steering_message=next_message,
                    )
                    keep_running = round_decision.action != "stop"
                    continue
                assistant_decision = self.turn_controller.after_assistant_turn(
                    self.state.queued_messages[0] if self.state.queued_messages else None
                )
                keep_running = assistant_decision.action != "stop"
                self._emit("turn_end", captured, details={"turn_id": self.state.turn_id})
        finally:
            self._finish_turn_node("cancelled" if cancelled else ("awaiting_approval" if self.state.phase == "awaiting_approval" else "completed"))
            if cancelled:
                self.state.phase = "cancelled"
                self._reset_prompt_tool_budget()
                self._emit(
                    "agent_cancelled",
                    captured,
                    message="Agent cancelled by user request.",
                    details={"turn_id": self.state.turn_id},
                )
            elif not self._restore_pending_tool_calls():
                self.state.phase = "idle"
                self._reset_prompt_tool_budget()
            self.state.is_running = False
            self._cancel_event.clear()
            if self._owns_cancellation_token:
                self.cancellation_token.reset()
            self._persist()
            self._emit("agent_end", captured, message="Agent ended.")
        return captured

    def _record_disabled_tool_calls(self, calls: list[ToolCall], captured: list[AgentEvent]) -> None:
        """Surface ignored provider tool calls without adding an invalid tool-call history entry."""
        blocked_calls = [call.to_dict() for call in calls]
        blocked_names = ", ".join(sorted({call.name for call in calls}))
        message = f"{_TOOLS_DISABLED_FALLBACK} Ignored requested tools: {blocked_names}."
        self.state.messages.append(ChatMessage.text("assistant", message))
        self._emit(
            "tool_error",
            captured,
            tool_name=calls[0].name,
            message=message,
            details={"reason": "tools_disabled", "blocked_tool_calls": blocked_calls},
            is_error=True,
        )
        self._emit("message", captured, message=message, details={"tools_enabled": False}, is_error=True)

    def _limit_response_tool_calls(
        self,
        calls: list[ToolCall],
        captured: list[AgentEvent],
        *,
        prompt_tool_calls_used: int,
    ) -> list[ToolCall]:
        """Keep one useful batch from a provider response without overriding tool choice."""
        if not calls:
            return []

        accepted: list[ToolCall] = []
        duplicate_calls: list[ToolCall] = []
        turn_overflow_calls: list[ToolCall] = []
        prompt_overflow_calls: list[ToolCall] = []
        seen: set[tuple[str, str]] = set()
        prompt_remaining = max(0, self.max_tool_calls_per_prompt - prompt_tool_calls_used)
        for call in calls:
            signature = self._tool_call_signature(call)
            if signature in seen:
                duplicate_calls.append(call)
                continue
            seen.add(signature)
            if len(accepted) >= self.max_tool_calls_per_turn:
                turn_overflow_calls.append(call)
                continue
            if len(accepted) >= prompt_remaining:
                prompt_overflow_calls.append(call)
                continue
            accepted.append(call)

        if duplicate_calls or turn_overflow_calls or prompt_overflow_calls:
            suppressed = [*duplicate_calls, *turn_overflow_calls, *prompt_overflow_calls]
            self._emit(
                "tool_calls_limited",
                captured,
                message=(
                    "Limited this model response to "
                    f"{len(accepted)} distinct tool call(s); skipped {len(suppressed)} redundant or excess call(s)."
                ),
                details={
                    "requested_count": len(calls),
                    "accepted_count": len(accepted),
                    "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
                    "max_tool_calls_per_prompt": self.max_tool_calls_per_prompt,
                    "prompt_tool_calls_used": prompt_tool_calls_used,
                    "prompt_tool_calls_remaining": prompt_remaining,
                    "duplicate_count": len(duplicate_calls),
                    "overflow_count": len(turn_overflow_calls) + len(prompt_overflow_calls),
                    "turn_overflow_count": len(turn_overflow_calls),
                    "prompt_budget_overflow_count": len(prompt_overflow_calls),
                    "suppressed_tool_calls": [call.to_dict() for call in suppressed],
                },
            )
        return accepted

    def _reset_prompt_tool_budget(self) -> None:
        self._prompt_tool_calls_used = 0
        self._prompt_tool_budget_active = False

    @staticmethod
    def _tool_call_signature(call: ToolCall) -> tuple[str, str]:
        """Use stable JSON so equivalent argument objects deduplicate reliably."""
        try:
            arguments = json.dumps(call.arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            arguments = repr(call.arguments)
        return call.name, arguments

    def _run_tool_limit_final_summary(self, captured: list[AgentEvent]) -> None:
        """Request one final answer after the allowed tool-driven turns are exhausted."""
        self.state.turn_id += 1
        self._begin_turn_node()
        self.state.phase = "planning"
        self._emit(
            "turn_start",
            captured,
            details={
                "turn_id": self.state.turn_id,
                "reason": "tool_turn_limit_final_summary",
                "tools_disabled": True,
            },
        )

        model_messages = self._messages_for_model()
        request_event = AgentEvent(
            type="before_provider_request",
            session_id=self.session_id,
            turn_id=self.state.turn_id,
            phase=self.state.phase,
        )
        request = self.emitter.emit_before_provider_request(request_event, self.state, model_messages, [])
        request_messages = list(request.messages if request.messages is not None else model_messages)
        request_messages.append(ChatMessage.text("system", _TOOL_LIMIT_FINAL_SUMMARY_INSTRUCTION))
        # This call must remain tool-free even when a lifecycle hook adds tools.
        request_tools: list[Any] = []
        self._emit(
            "before_provider_request",
            captured,
            details={
                "message_count": len(request_messages),
                "tool_count": 0,
                "forced_final_summary": True,
            },
        )

        try:
            response = self._collect_provider_response(request_messages, request_tools, captured)
        except Exception as exc:  # noqa: BLE001 - preserve completed tool observations for the user
            message = f"{_TOOL_LIMIT_FINAL_FALLBACK} The final no-tool response failed."
            self.state.messages.append(ChatMessage.text("assistant", message))
            self._emit(
                "provider_error",
                captured,
                message=message,
                details={"reason": "tool_turn_limit_final_summary", "error": str(exc)},
                is_error=True,
            )
            self._emit("message", captured, message=message, details={"forced_final_summary": True}, is_error=True)
            self._emit("turn_end", captured, details={"turn_id": self.state.turn_id, "forced_final_summary": True, "status": "provider_error"})
            return

        response_event = AgentEvent(
            type="provider_response",
            session_id=self.session_id,
            turn_id=self.state.turn_id,
            phase=self.state.phase,
        )
        response_decision = self.emitter.emit_provider_response(response_event, response.text, response.tool_calls)
        if response_decision.assistant_text is not None:
            response.text = response_decision.assistant_text
        if response_decision.tool_calls is not None:
            response.tool_calls = response_decision.tool_calls

        if response.text:
            self.state.messages.append(ChatMessage.text("assistant", response.text))
            self._emit("message", captured, message=response.text, details={"forced_final_summary": True})

        if response.tool_calls:
            blocked_calls = [call.to_dict() for call in response.tool_calls]
            blocked_names = ", ".join(sorted({call.name for call in response.tool_calls}))
            message = (
                f"{_TOOL_LIMIT_FINAL_FALLBACK} I did not execute the additional requested tool calls: "
                f"{blocked_names}."
            )
            self.state.messages.append(ChatMessage.text("assistant", message))
            self._emit(
                "tool_error",
                captured,
                tool_name=response.tool_calls[0].name,
                message=message,
                details={
                    "reason": "tool_turn_limit",
                    "blocked_tool_calls": blocked_calls,
                    "forced_final_summary": True,
                },
                is_error=True,
            )
            self._emit("message", captured, message=message, details={"forced_final_summary": True}, is_error=True)
        elif not response.text.strip():
            message = f"{_TOOL_LIMIT_FINAL_FALLBACK} The model did not provide a final answer."
            self.state.messages.append(ChatMessage.text("assistant", message))
            self._emit("message", captured, message=message, details={"forced_final_summary": True}, is_error=True)

        self._emit("turn_end", captured, details={"turn_id": self.state.turn_id, "forced_final_summary": True})

    def _collect_provider_response(
        self,
        messages: list[ChatMessage],
        tools: list[Any],
        captured: list[AgentEvent],
    ) -> LLMResponse:
        """Collect a streamed or complete provider result into one response object."""
        text_parts: list[str] = []
        streamed_tool_calls: list[ToolCall] = []
        streamed_usage: dict[str, int] = {}
        streamed_metadata: dict[str, Any] = {}
        for chunk in iter_provider_stream(self.llm, messages, tools):
            if chunk.text:
                text_parts.append(chunk.text)
                self._emit("message_delta", captured, delta=chunk.text)
            if chunk.tool_calls:
                streamed_tool_calls.extend(chunk.tool_calls)
            if chunk.usage:
                streamed_usage.update(chunk.usage)
            if chunk.provider_metadata:
                streamed_metadata.update(chunk.provider_metadata)
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=streamed_tool_calls,
            usage=streamed_usage,
            provider_metadata=streamed_metadata,
        )

    def _messages_for_model(self) -> list[ChatMessage]:
        """构造发给模型的上下文，并在调用前注入相关长期记忆。"""
        messages = [ChatMessage.text("system", self.state.system_prompt)]
        messages.extend(self._tool_protocol_safe_history(token_budget=self.history_token_budget))
        if self.memory_provider is not None:
            messages = self.memory_provider.transform_context(self.state, messages)
        built = AgentEvent(type="context_built", session_id=self.session_id, turn_id=self.state.turn_id, phase=self.state.phase)
        transformed = self.emitter.emit_context_built(built, self.state, messages).messages
        if transformed is not None:
            messages = transformed
        return messages

    def _tool_protocol_safe_history(self, *, token_budget: int) -> list[ChatMessage]:
        """按估算 token 预算截取历史，并保留 OpenAI 工具调用协议的完整单元。"""
        selected: list[list[ChatMessage]] = []
        remaining = token_budget
        for unit in reversed(self._history_units(self.state.messages)):
            safe_unit = self._sanitize_tool_protocol(unit)
            if not safe_unit:
                continue
            estimated = self._estimate_messages_tokens(safe_unit)
            if estimated <= remaining:
                selected.append(safe_unit)
                remaining -= estimated
                continue
            if not selected:
                selected.append(self._truncate_unit_to_budget(safe_unit, token_budget))
            # 保持一段连续的最近历史；遇到第一个放不下的旧单元后停止向前扩展。
            break
        return [message for unit in reversed(selected) for message in unit]

    @staticmethod
    def _history_units(history: list[ChatMessage]) -> list[list[ChatMessage]]:
        """将 assistant tool_calls 与其连续的 tool 响应组合为不可拆分的上下文单元。"""
        units: list[list[ChatMessage]] = []
        index = 0
        while index < len(history):
            message = history[index]
            if message.role == "assistant" and message.tool_calls:
                next_index = index + 1
                while next_index < len(history) and history[next_index].role == "tool":
                    next_index += 1
                units.append(history[index:next_index])
                index = next_index
                continue
            units.append([message])
            index += 1
        return units

    def _truncate_unit_to_budget(self, messages: list[ChatMessage], token_budget: int) -> list[ChatMessage]:
        """保留最近单元的协议字段，仅截断其文本内容以接近预算。"""
        if len(messages) == 1 and messages[0].role == "user":
            # 当前用户输入是本轮任务边界，宁可软性超预算也不能截成不完整指令。
            return messages
        overhead = sum(self._estimate_message_tokens(message, include_content=False) for message in messages)
        text_budget = max(0, token_budget - overhead)
        text_sizes = [self._estimate_text_tokens(message.text_content()) for message in messages]
        truncated: list[ChatMessage] = []
        remaining = text_budget
        for index, message in enumerate(messages):
            remaining_messages = len(messages) - index
            share = min(text_sizes[index], max(0, remaining // remaining_messages))
            truncated.append(self._truncate_message_text(message, share))
            remaining -= share
        return truncated

    @classmethod
    def _truncate_message_text(cls, message: ChatMessage, token_budget: int) -> ChatMessage:
        """复制消息并将正文截断到近似 token 预算，保留工具调用标识。"""
        text = message.text_content()
        if cls._estimate_text_tokens(text) <= token_budget:
            return message
        if token_budget <= 0:
            shortened = "[truncated]"
        else:
            ratio = min(1.0, token_budget / max(1, cls._estimate_text_tokens(text)))
            limit = max(1, int(len(text) * ratio) - len("\n[truncated]"))
            shortened = f"{text[:limit]}\n[truncated]"
        return ChatMessage(
            role=message.role,
            content=[TextPart(text=shortened)],
            tool_call_id=message.tool_call_id,
            tool_name=message.tool_name,
            tool_calls=list(message.tool_calls),
            metadata=dict(message.metadata),
            timestamp=message.timestamp,
        )

    @classmethod
    def _estimate_messages_tokens(cls, messages: list[ChatMessage]) -> int:
        """返回消息列表的保守 token 估算值，不依赖特定模型的 tokenizer。"""
        return sum(cls._estimate_message_tokens(message) for message in messages)

    @classmethod
    def _estimate_message_tokens(cls, message: ChatMessage, *, include_content: bool = True) -> int:
        """估算单条消息正文及工具调用结构占用的 token。"""
        tokens = 4 + cls._estimate_text_tokens(message.tool_name or "")
        if message.tool_call_id:
            tokens += cls._estimate_text_tokens(message.tool_call_id)
        for call in message.tool_calls:
            tokens += cls._estimate_text_tokens(call.name)
            tokens += cls._estimate_text_tokens(json.dumps(call.arguments, ensure_ascii=False, sort_keys=True))
        if include_content:
            tokens += cls._estimate_text_tokens(message.text_content())
        return tokens

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        """用 ASCII 每四字符、非 ASCII 每字符的保守规则估算 token 数。"""
        ascii_chars = sum(1 for char in text if ord(char) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return (ascii_chars + 3) // 4 + non_ascii_chars

    def _sanitize_tool_protocol(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """移除或降级孤立 tool 消息，避免发送给模型的上下文违反工具调用协议。"""
        safe: list[ChatMessage] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "tool":
                safe.append(self._tool_observation_as_assistant(message))
                index += 1
                continue
            if message.role != "assistant" or not message.tool_calls:
                safe.append(message)
                index += 1
                continue

            tool_messages: list[ChatMessage] = []
            next_index = index + 1
            call_ids = {call.id for call in message.tool_calls}
            while next_index < len(messages) and messages[next_index].role == "tool":
                tool_message = messages[next_index]
                if tool_message.tool_call_id in call_ids:
                    tool_messages.append(tool_message)
                else:
                    safe.append(self._tool_observation_as_assistant(tool_message))
                next_index += 1

            answered_ids = {tool_message.tool_call_id for tool_message in tool_messages}
            answered_calls = [call for call in message.tool_calls if call.id in answered_ids]
            if answered_calls:
                safe.append(
                    ChatMessage(
                        role="assistant",
                        content=[TextPart(text=part.text, type=part.type) for part in message.content],
                        tool_calls=answered_calls,
                        metadata=dict(message.metadata),
                        timestamp=message.timestamp,
                    )
                )
                safe.extend(tool_messages)
            elif message.text_content().strip():
                safe.append(ChatMessage.text("assistant", message.text_content()))
            index = next_index
        return safe

    @staticmethod
    def _tool_observation_as_assistant(message: ChatMessage) -> ChatMessage:
        """把无法配对的 tool 结果改写成普通助手观察，避免 provider 拒绝请求。"""
        name = message.tool_name or message.tool_call_id or "unknown tool"
        text = message.text_content() or "(empty tool result)"
        return ChatMessage.text("assistant", f"Tool observation from {name}:\n{text}")

    def _stage_approval(self, planned: PlannedToolCall, *, plan_id: str):
        """Persist the Planner's exact-effect contract without recomputing it."""
        if self.approval_store is None:
            raise RuntimeError("Approval store is not configured.")
        details = planned.approval_details(plan_id=plan_id)
        # Bind the approval to its turn-DAG head.  Session ids alone are not a
        # sufficient capability boundary once sibling heads can be resumed.
        details["head_id"] = self.session.active_head_id
        return self.approval_store.create(
            session_id=self.session_id,
            call=planned.call,
            reason=planned.reason,
            details=details,
        )

    def _restore_pending_tool_calls(self) -> bool:
        """从持久化审批恢复当前会话的未决调用，支持进程重启后继续同一工具批次。"""
        if self.approval_store is None:
            return bool(self.state.pending_tool_calls)
        session_approvals = [
            approval
            for approval in self.approval_store.list(status=None)
            if approval.session_id == self.session_id
        ]
        approvals = [
            approval
            for approval in session_approvals
            if self._approval_on_active_head(approval)
        ]
        pending = [approval for approval in approvals if approval.status == "pending"]
        unresolved = [
            approval
            for approval in approvals
            if approval.execution_status == "executing" and approval.status != "pending"
        ]
        blocking = [*pending, *unresolved]
        session_unresolved = [
            approval
            for approval in session_approvals
            if approval.execution_status == "executing"
        ]
        self.state.pending_tool_calls = [
            ToolCall(
                id=approval.tool_call_id,
                name=approval.tool_name,
                arguments=dict(approval.arguments),
            )
            for approval in reversed(blocking)
        ]
        if blocking or session_unresolved:
            plan_ids = [str(approval.details.get("plan_id") or "") for approval in blocking]
            self.state.pending_plan_token = next((plan_id for plan_id in plan_ids if plan_id), None) if blocking else None
            self.state.phase = "execution_recovery_required" if session_unresolved else "awaiting_approval"
        return bool(blocking or session_unresolved)

    def _require_no_unresolved_session_execution(self) -> None:
        """Keep new side effects out of a workspace with an ambiguous in-flight one."""
        if self.approval_store is None:
            return
        unresolved_ids = [
            approval.approval_id
            for approval in self.approval_store.list(status=None)
            if approval.session_id == self.session_id and approval.execution_status == "executing"
        ]
        if unresolved_ids:
            raise RuntimeError(
                "Cannot execute a pending approval while another approval execution is unresolved: "
                + ", ".join(unresolved_ids)
            )

    def _require_approval_on_active_head(self, approval: PendingApproval) -> None:
        """Reject cross-head approval use without changing the original record."""
        if self._approval_on_active_head(approval):
            return
        approval_head_id = str(approval.details.get("head_id") or "legacy-message-context")
        active_head_id = str(self.session.active_head_id or "none")
        raise ValueError(
            "Approval belongs to a different session head "
            f"(approval_head={approval_head_id}, active_head={active_head_id}). "
            "Switch to the originating head before approving or rejecting it."
        )

    def _approval_on_active_head(self, approval: PendingApproval) -> bool:
        """Return whether an approval is visible from the selected turn-DAG head."""
        approval_head_id = str(approval.details.get("head_id") or "")
        if approval_head_id:
            return self._head_descends_from(self.session.active_head_id, approval_head_id)
        # Pre-head-binding approvals remain usable only where their originating
        # tool call is still present in the active conversation snapshot.
        return any(
            call.id == approval.tool_call_id
            and call.name == approval.tool_name
            and call.arguments == approval.arguments
            for message in self.state.messages
            for call in message.tool_calls
        )

    def _head_descends_from(self, head_id: str | None, ancestor_head_id: str) -> bool:
        """Check whether ``head_id`` is the approval head or one of its descendants."""
        cursor = str(head_id or "")
        if not cursor:
            return False
        nodes = {
            str(node.get("turn_node_id") or ""): node
            for node in self.session.turns
            if str(node.get("turn_node_id") or "")
        }
        seen: set[str] = set()
        while cursor and cursor not in seen:
            if cursor == ancestor_head_id:
                return True
            seen.add(cursor)
            node = nodes.get(cursor)
            if node is None:
                return False
            cursor = str(node.get("parent_head_id") or "")
        return False

    def _continue_after_approval_resolution(self, captured: list[AgentEvent]) -> list[AgentEvent]:
        """等待同批其他审批完成；最后一个审批解决后才重新调用模型。"""
        if self._restore_pending_tool_calls():
            self._persist()
            return captured
        self.state.pending_plan_token = None
        captured.extend(self._run_loop())
        return captured

    def _record_approved_execution_failure(
        self,
        approval_id: str,
        failure: ToolExecutionError,
        captured: list[AgentEvent],
    ) -> None:
        """Record a terminal approved-tool failure without making it retryable."""
        call = failure.call
        self.emitter.emit_tool_error(
            captured[-1] if captured else AgentEvent(
                type="tool_error",
                session_id=self.session_id,
                turn_id=self.state.turn_id,
                phase=self.state.phase,
            ),
            self.state,
            call,
            failure.cause,
        )
        self._append_tool_error(call, str(failure))
        self.state.pending_tool_calls = [item for item in self.state.pending_tool_calls if item.id != call.id]
        self._persist()
        details = {
            "approval_id": approval_id,
            "execution_id": failure.execution_id,
            "execution_status": "failed",
        }
        self._emit(
            "approval_failed",
            captured,
            tool_name=call.name,
            message=str(failure),
            details=details,
            is_error=True,
        )
        self._emit(
            "tool_error",
            captured,
            tool_name=call.name,
            message=str(failure),
            details=details,
            is_error=True,
        )

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
        metadata = {
            **metadata,
            "head_id": self.session.active_head_id,
            "turn_id": self.state.turn_id,
            "approval_states": self._checkpoint_approval_states(),
        }
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

    def _checkpoint_approval_states(self) -> dict[str, dict[str, Any]]:
        """Capture approval state so rewind can retain only checkpoint-consistent effects."""
        if self.approval_store is None:
            return {}
        return {
            approval.approval_id: {
                "status": approval.status,
                "execution_status": approval.execution_status,
                "execution_id": approval.execution_id,
                "updated_at": approval.updated_at,
            }
            for approval in self.approval_store.list(status=None)
            if approval.session_id == self.session_id and self._approval_on_active_head(approval)
        }

    def _reconcile_approvals_for_rewind(self, checkpoint: CheckpointRecord) -> dict[str, list[str]]:
        """Prevent post-checkpoint approvals from surviving a conversation rewind."""
        if self.approval_store is None:
            return {"invalidated": [], "retained": [], "blockers": []}
        states = checkpoint.metadata.get("approval_states")
        snapshots = (
            {str(key): dict(value) for key, value in states.items() if isinstance(value, dict)}
            if isinstance(states, dict)
            else {}
        )
        return self.approval_store.reconcile_for_rewind(
            session_id=self.session_id,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_created_at=checkpoint.created_at,
            checkpoint_approvals=snapshots,
            approval_ids={
                approval.approval_id
                for approval in self.approval_store.list(status=None)
                if approval.session_id == self.session_id and self._approval_on_active_head(approval)
            },
        )

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
        self.session.system_prompt = self.state.system_prompt
        self.session.messages = self.state.messages
        self.session.queued_messages = list(self.state.queued_messages)
        self.session.active_head_id = self.session.active_head_id
        self.session.turns = list(self.session.turns)
        self.session_store.save(self.session)

    def _begin_turn_node(self) -> None:
        """Append a lightweight turn-DAG node without changing message storage."""
        if self.session.turns and self.session.turns[-1].get("status") == "running":
            self.session.turns[-1]["status"] = "completed"
        node_id = str(uuid.uuid4())
        self._active_turn_node_id = node_id
        self.session.turns.append({
            "turn_id": self.state.turn_id,
            "turn_node_id": node_id,
            "parent_head_id": self.session.active_head_id,
            "status": "running",
            "started_at": time.time(),
            "message_count": len(self.state.messages),
        })
        self.session.active_head_id = node_id

    def _finish_turn_node(self, status: str) -> None:
        if not self._active_turn_node_id:
            return
        for node in reversed(self.session.turns):
            if node.get("turn_node_id") == self._active_turn_node_id:
                node["status"] = status
                node["finished_at"] = time.time()
                node["message_count"] = len(self.state.messages)
                break
        self._active_turn_node_id = None

    def _emit(
        self,
        event_type: str,
        captured: list[AgentEvent],
        *,
        message: str | None = None,
        delta: str | None = None,
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
            delta=delta,
            tool_name=tool_name,
            details=details or {},
            is_error=is_error,
        )
        captured.append(event)
        self.emitter.emit(event)
        if self.timeline_store is not None:
            self.timeline_store.append(event)
        for subscriber in self._subscribers:
            subscriber(event)
