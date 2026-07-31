from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.domain.tools import ToolCall, ToolSpec
from codemuse.app.bootstrap import build_agent
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.runtime.executor import ApprovalValidationError, Executor, ToolExecutionError
from codemuse.runtime.planner import Planner
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.tools.base import BaseTool, ToolResult
from codemuse.tools.policy import ASK, DENY, ToolPolicyEvaluator
from codemuse.tools.registry import ToolRegistry
from codemuse.tools.validation import ToolArgumentValidationError


class _RecordingTool(BaseTool):
    def __init__(self, workspace: Path, store: PendingApprovalStore, *, fail: bool = False) -> None:
        super().__init__(workspace)
        self.store = store
        self.fail = fail
        self.executions = 0
        self.observed_execution_status: str | None = None
        self.observed_execution_id: str | None = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="record_effect",
            description="Record one test side effect.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer", "minimum": 1}},
                "required": ["value"],
                "additionalProperties": False,
            },
            permission_domain="write",
            requires_confirmation=True,
            side_effect=True,
        )

    def execute(self, arguments: dict) -> ToolResult:
        self.executions += 1
        approval = self.store.list()[0]
        self.observed_execution_status = approval.execution_status
        self.observed_execution_id = approval.execution_id
        if self.fail:
            raise RuntimeError("planned failure")
        return ToolResult(tool_name=self.spec.name, content=f"recorded {arguments['value']}")


class _SequencedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self._info = LLMProviderInfo(provider="test", model="planner-executor")

    @property
    def info(self) -> LLMProviderInfo:
        return self._info

    def complete(self, _messages, _tools) -> LLMResponse:
        if not self.responses:
            raise AssertionError("Unexpected provider call")
        return self.responses.pop(0)


class PlannerExecutorTests(unittest.TestCase):
    def test_runtime_delegates_provider_calls_to_planner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            agent.llm = _SequencedLLM([
                LLMResponse(tool_calls=[
                    ToolCall(id="invalid", name="list_files", arguments={"path": 42}),
                    ToolCall(id="unknown", name="not_registered", arguments={}),
                ]),
                LLMResponse(text="invalid calls were contained"),
            ])

            events = agent.prompt("exercise planner boundary")

            plan_event = next(event for event in events if event.type == "plan_created")
            self.assertEqual(plan_event.details["denied_count"], 2)
            self.assertIsNotNone(agent.last_plan)
            self.assertEqual(len(agent.last_plan.tool_calls), 2)
            self.assertEqual(agent.last_plan.tool_calls[0].details["gate"], "argument_validation")
            self.assertEqual(agent.last_plan.tool_calls[1].details["gate"], "tool_lookup")
            self.assertEqual(len([event for event in events if event.type == "tool_error"]), 2)
            self.assertFalse(any(event.type == "tool_result" for event in events))
            self.assertEqual(agent.state.phase, "idle")

    def test_planner_validates_before_policy_and_binds_approval_effect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = PendingApprovalStore(root / "approvals")
            registry = ToolRegistry(root)
            tool = _RecordingTool(root, store)
            registry.register(tool)
            planner = Planner(
                workspace=root,
                tool_registry=registry,
                policy_evaluator=ToolPolicyEvaluator(),
            )

            invalid_plan = planner.create_plan(
                session_id="session",
                turn_id=1,
                tool_calls=[ToolCall(id="bad", name="record_effect", arguments={"value": "1"})],
            )
            invalid = invalid_plan.tool_calls[0]

            self.assertEqual(invalid.action, DENY)
            self.assertEqual(invalid.details["gate"], "argument_validation")
            self.assertTrue(invalid.validation_errors)
            self.assertEqual(tool.executions, 0)

            plan = planner.create_plan(
                session_id="session",
                turn_id=2,
                tool_calls=[ToolCall(id="good", name="record_effect", arguments={"value": 1})],
            )
            planned = plan.tool_calls[0]

            self.assertEqual(planned.action, ASK)
            approval_details = planned.approval_details(plan_id=plan.plan_id)
            self.assertTrue(approval_details["exact_effect_approval"])
            self.assertEqual(approval_details["plan_id"], plan.plan_id)
            self.assertTrue(approval_details["effect_digest"])

    def test_registry_rejects_invalid_arguments_before_tool_code(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = PendingApprovalStore(root / "approvals")
            registry = ToolRegistry(root)
            tool = _RecordingTool(root, store)
            registry.register(tool)

            with self.assertRaises(ToolArgumentValidationError):
                registry.execute("record_effect", {"value": 0, "unexpected": True})

            self.assertEqual(tool.executions, 0)

    def test_approved_execution_is_claimed_completed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store, tool, plan, approval = self._stage_call(root)
            executor = Executor(workspace=root, tool_registry=self._registry(root, tool), approval_store=store)

            outcome = executor.execute_approved(approval.approval_id, session_id="session")
            completed = store.load(approval.approval_id)

            self.assertEqual(tool.observed_execution_status, "executing")
            self.assertEqual(tool.observed_execution_id, outcome.execution_id)
            self.assertEqual(completed.status, "approved")
            self.assertEqual(completed.execution_status, "completed")
            self.assertEqual(completed.execution_id, outcome.execution_id)
            self.assertIsNotNone(completed.execution_started_at)
            self.assertIsNotNone(completed.execution_finished_at)

            replay = executor.execute_approved(approval.approval_id, session_id="session")

            self.assertTrue(replay.replayed)
            self.assertEqual(replay.execution_id, outcome.execution_id)
            self.assertEqual(tool.executions, 1)
            self.assertEqual(plan.plan_id, completed.details["plan_id"])

    def test_failed_execution_is_terminal_and_never_returns_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = PendingApprovalStore(root / "approvals")
            tool = _RecordingTool(root, store, fail=True)
            registry = self._registry(root, tool)
            planner = Planner(workspace=root, tool_registry=registry, policy_evaluator=ToolPolicyEvaluator())
            plan = planner.create_plan(
                session_id="session",
                turn_id=1,
                tool_calls=[ToolCall(id="call", name="record_effect", arguments={"value": 1})],
            )
            planned = plan.tool_calls[0]
            approval = store.create(
                session_id="session",
                call=planned.call,
                reason=planned.reason,
                details=planned.approval_details(plan_id=plan.plan_id),
            )
            executor = Executor(workspace=root, tool_registry=registry, approval_store=store)

            with self.assertRaises(ToolExecutionError):
                executor.execute_approved(approval.approval_id, session_id="session")

            failed = store.load(approval.approval_id)
            self.assertEqual(failed.status, "approved")
            self.assertEqual(failed.execution_status, "failed")
            self.assertTrue(failed.execution_id)
            with self.assertRaisesRegex(RuntimeError, "requires a new plan"):
                executor.execute_approved(approval.approval_id, session_id="session")
            self.assertEqual(tool.executions, 1)

    def test_tampered_approval_is_invalidated_before_execution_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store, tool, _plan, approval = self._stage_call(root)
            approval.arguments["value"] = 2
            store.save(approval)
            executor = Executor(workspace=root, tool_registry=self._registry(root, tool), approval_store=store)

            with self.assertRaises(ApprovalValidationError) as raised:
                executor.execute_approved(approval.approval_id, session_id="session")

            invalid = store.load(approval.approval_id)
            self.assertEqual(raised.exception.status, "invalid")
            self.assertEqual(invalid.status, "invalid")
            self.assertEqual(invalid.execution_status, "cancelled")
            self.assertIsNone(invalid.execution_id)
            self.assertEqual(tool.executions, 0)

    def test_write_approval_rechecks_target_after_before_execute_callback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "README.md"
            target.write_text("# Original\n", encoding="utf-8")
            agent = build_agent(root)
            agent.memory_provider = None
            staged = agent.prompt("write file README.md content: # Approved")
            approval_id = str(next(event.details["approval_id"] for event in staged if event.type == "approval_required"))

            def mutate_target(_call: ToolCall, _execution_id: str) -> None:
                target.write_text("# Raced target\n", encoding="utf-8")

            with self.assertRaises(ApprovalValidationError) as raised:
                agent.executor.execute_approved(
                    approval_id,
                    session_id=agent.session_id,
                    before_execute=mutate_target,
                )

            approval = agent.approval_store.load(approval_id)
            self.assertEqual(raised.exception.status, "stale")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Raced target\n")
            self.assertEqual(approval.status, "stale")
            self.assertEqual(approval.execution_status, "cancelled")
            self.assertEqual(approval.details["stale_gate"], "execution_boundary")

    @staticmethod
    def _registry(root: Path, tool: _RecordingTool) -> ToolRegistry:
        registry = ToolRegistry(root)
        registry.register(tool)
        return registry

    def _stage_call(self, root: Path):
        store = PendingApprovalStore(root / "approvals")
        tool = _RecordingTool(root, store)
        registry = self._registry(root, tool)
        planner = Planner(workspace=root, tool_registry=registry, policy_evaluator=ToolPolicyEvaluator())
        plan = planner.create_plan(
            session_id="session",
            turn_id=1,
            tool_calls=[ToolCall(id="call", name="record_effect", arguments={"value": 1})],
        )
        planned = plan.tool_calls[0]
        approval = store.create(
            session_id="session",
            call=planned.call,
            reason=planned.reason,
            details=planned.approval_details(plan_id=plan.plan_id),
        )
        return store, tool, plan, approval


if __name__ == "__main__":
    unittest.main()
