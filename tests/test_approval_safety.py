"""验证 approval safety 相关功能在对外行为上符合预期。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codemuse.app.bootstrap import build_agent
from codemuse.domain.tools import ToolSpec
from codemuse.storage.approvals import PendingApprovalStore
from codemuse.tools.policy import ALLOW, ASK, ToolPolicyEvaluator


class ApprovalSafetyTests(unittest.TestCase):
    """ApprovalSafetyTests：组织该功能的单元测试用例。"""
    def test_policy_allows_read_and_asks_for_side_effects(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        policy = ToolPolicyEvaluator()

        read_decision = policy.evaluate(ToolSpec(name="read_file", description="read"))
        write_decision = policy.evaluate(
            ToolSpec(name="save_blueprint_memory", description="save", permission_domain="write", side_effect=True)
        )

        self.assertEqual(read_decision.action, ALLOW)
        self.assertEqual(write_decision.action, ASK)

    def test_runtime_stages_and_approves_side_effect_tool(self) -> None:
        """验证该场景下的输入、状态变化和输出是否符合预期。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            agent = build_agent(root)
            events = agent.prompt("学习仓库并作为记忆")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            approval_id = str(approval_events[0].details["approval_id"])

            store = PendingApprovalStore(root / ".data" / "codemuse" / "approvals")
            pending = store.load(approval_id)
            self.assertEqual(pending.status, "pending")
            self.assertEqual(pending.tool_name, "save_blueprint_memory")

            approved_events = agent.approve(approval_id)
            approved = store.load(approval_id)

            self.assertEqual(approved.status, "approved")
            self.assertTrue(any(event.type == "approval_approved" for event in approved_events))
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "save_blueprint_memory" for event in approved_events))

    def test_write_file_requires_approval_before_disk_change(self) -> None:
        """验证 write_file 先进入审批，批准后才真正写入 workspace。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "notes" / "hello.txt"

            agent = build_agent(root)
            events = agent.prompt("write file notes/hello.txt content: hello from approval")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            self.assertFalse(target.exists())
            approval_id = str(approval_events[0].details["approval_id"])
            preview = approval_events[0].details["effect_preview"]
            self.assertEqual(preview["kind"], "write_file")
            self.assertEqual(preview["operation"], "create")
            self.assertEqual(preview["relative_path"], "notes/hello.txt")
            self.assertIn("+hello from approval", preview["diff"])

            pending = PendingApprovalStore(root / ".data" / "codemuse" / "approvals").load(approval_id)
            self.assertEqual(pending.tool_name, "write_file")
            self.assertEqual(pending.details["effect_preview"]["relative_path"], "notes/hello.txt")

            approved_events = agent.approve(approval_id)

            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "hello from approval\n")
            self.assertTrue(any(event.type == "checkpoint_created" and event.tool_name == "write_file" for event in approved_events))
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "write_file" for event in approved_events))

    def test_write_file_approval_preview_contains_diff_for_existing_file(self) -> None:
        """验证覆盖已有文件前，approval 事件会展示可审查的 diff。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            agent = build_agent(root)
            events = agent.prompt("write file README.md content: # Changed")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            preview = approval_events[0].details["effect_preview"]

            self.assertEqual(preview["operation"], "update")
            self.assertEqual(preview["relative_path"], "README.md")
            self.assertGreater(preview["before_chars"], preview["after_chars"])
            self.assertIn("-# Sample Agent", preview["diff"])
            self.assertIn("+# Changed", preview["diff"])

    def test_write_file_approval_becomes_stale_when_target_changes(self) -> None:
        """验证批准前目标文件发生变化时，Runtime 会拒绝按旧 diff 执行写入。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"

            agent = build_agent(root)
            events = agent.prompt("write file README.md content: # Changed by agent")
            approval_events = [event for event in events if event.type == "approval_required"]
            approval_id = str(approval_events[0].details["approval_id"])
            target.write_text("# Changed outside approval\n", encoding="utf-8")

            approved_events = agent.approve(approval_id)
            pending = PendingApprovalStore(root / ".data" / "codemuse" / "approvals").load(approval_id)

            self.assertEqual(pending.status, "stale")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Changed outside approval\n")
            self.assertTrue(any(event.type == "approval_stale" and event.tool_name == "write_file" for event in approved_events))
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "write_file" for event in approved_events))

    def test_write_file_approval_becomes_invalid_when_arguments_are_tampered(self) -> None:
        """验证审批单参数被篡改后，Runtime 会用 digest 拦截并拒绝执行。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            original_target = root / "notes" / "original.txt"
            tampered_target = root / "notes" / "tampered.txt"

            agent = build_agent(root)
            events = agent.prompt("write file notes/original.txt content: original content")
            approval_events = [event for event in events if event.type == "approval_required"]
            approval_id = str(approval_events[0].details["approval_id"])

            store = PendingApprovalStore(root / ".data" / "codemuse" / "approvals")
            pending = store.load(approval_id)
            pending.arguments["path"] = "notes/tampered.txt"
            pending.arguments["content"] = "tampered content\n"
            store.save(pending)

            approved_events = agent.approve(approval_id)
            updated = store.load(approval_id)

            self.assertEqual(updated.status, "invalid")
            self.assertFalse(original_target.exists())
            self.assertFalse(tampered_target.exists())
            self.assertTrue(any(event.type == "approval_invalid" and event.tool_name == "write_file" for event in approved_events))
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "write_file" for event in approved_events))

    def test_replace_text_requires_approval_and_replaces_after_approval(self) -> None:
        """验证 replace_text 先展示 diff 等待审批，批准后才替换目标文本。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"

            agent = build_agent(root)
            events = agent.prompt("replace text README.md old: # Sample Agent new: # Replaced Agent")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            self.assertEqual(target.read_text(encoding="utf-8").splitlines()[0], "# Sample Agent")
            preview = approval_events[0].details["effect_preview"]
            self.assertEqual(preview["kind"], "replace_text")
            self.assertEqual(preview["relative_path"], "README.md")
            self.assertEqual(preview["match_count"], 1)
            self.assertEqual(preview["replacements"], 1)
            self.assertIn("-# Sample Agent", preview["diff"])
            self.assertIn("+# Replaced Agent", preview["diff"])

            approved_events = agent.approve(str(approval_events[0].details["approval_id"]))

            self.assertEqual(target.read_text(encoding="utf-8").splitlines()[0], "# Replaced Agent")
            self.assertTrue(any(event.type == "checkpoint_created" and event.tool_name == "replace_text" for event in approved_events))
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "replace_text" for event in approved_events))

    def test_replace_text_becomes_stale_when_target_changes(self) -> None:
        """验证 replace_text 批准前目标文件变化时，会复用 stale guard 拒绝执行。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"

            agent = build_agent(root)
            events = agent.prompt("replace text README.md old: # Sample Agent new: # Replaced Agent")
            approval_id = str([event for event in events if event.type == "approval_required"][0].details["approval_id"])
            target.write_text("# Changed outside replace\n", encoding="utf-8")

            approved_events = agent.approve(approval_id)
            pending = PendingApprovalStore(root / ".data" / "codemuse" / "approvals").load(approval_id)

            self.assertEqual(pending.status, "stale")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Changed outside replace\n")
            self.assertTrue(any(event.type == "approval_stale" and event.tool_name == "replace_text" for event in approved_events))
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "replace_text" for event in approved_events))

    def test_apply_patch_requires_approval_and_applies_after_approval(self) -> None:
        """验证 apply_patch 会先进入审批，批准后才应用 unified diff。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"
            patch = "\n".join(
                [
                    "--- a/README.md",
                    "+++ b/README.md",
                    "@@ -1,3 +1,3 @@",
                    "-# Sample Agent",
                    "+# Patched Agent",
                    " ",
                    " A tiny coding agent that can save blueprint memory.",
                ]
            )

            agent = build_agent(root)
            events = agent.prompt(f"apply patch patch:\n{patch}")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            self.assertEqual(target.read_text(encoding="utf-8").splitlines()[0], "# Sample Agent")
            preview = approval_events[0].details["effect_preview"]
            self.assertEqual(preview["kind"], "apply_patch")
            self.assertEqual(preview["files_count"], 1)
            self.assertEqual(preview["changes"][0]["relative_path"], "README.md")
            self.assertIn("-# Sample Agent", preview["changes"][0]["diff"])
            self.assertIn("+# Patched Agent", preview["changes"][0]["diff"])

            approved_events = agent.approve(str(approval_events[0].details["approval_id"]))

            self.assertEqual(target.read_text(encoding="utf-8").splitlines()[0], "# Patched Agent")
            self.assertTrue(any(event.type == "checkpoint_created" and event.tool_name == "apply_patch" for event in approved_events))
            self.assertTrue(any(event.type == "tool_result" and event.tool_name == "apply_patch" for event in approved_events))

    def test_apply_patch_becomes_stale_when_target_changes(self) -> None:
        """验证 apply_patch 批准前目标文件变化时，会复用 stale guard 拒绝执行。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"
            patch = "\n".join(
                [
                    "--- a/README.md",
                    "+++ b/README.md",
                    "@@ -1,3 +1,3 @@",
                    "-# Sample Agent",
                    "+# Patched Agent",
                    " ",
                    " A tiny coding agent that can save blueprint memory.",
                ]
            )

            agent = build_agent(root)
            events = agent.prompt(f"apply patch patch:\n{patch}")
            approval_id = str([event for event in events if event.type == "approval_required"][0].details["approval_id"])
            target.write_text("# Changed outside patch\n", encoding="utf-8")

            approved_events = agent.approve(approval_id)
            pending = PendingApprovalStore(root / ".data" / "codemuse" / "approvals").load(approval_id)

            self.assertEqual(pending.status, "stale")
            self.assertEqual(target.read_text(encoding="utf-8"), "# Changed outside patch\n")
            self.assertTrue(any(event.type == "approval_stale" and event.tool_name == "apply_patch" for event in approved_events))
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "apply_patch" for event in approved_events))

    def test_run_shell_requires_approval_and_runs_after_approval(self) -> None:
        """验证 run_shell 先展示风险预览，批准后才执行命令。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)

            agent = build_agent(root)
            events = agent.prompt('run shell command: python -c "print(\'shell ok\')"')
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "run_shell" for event in events))
            preview = approval_events[0].details["effect_preview"]
            self.assertEqual(preview["kind"], "run_shell")
            self.assertEqual(preview["command"], 'python -c "print(\'shell ok\')"')
            self.assertFalse(preview["blocked"])
            self.assertIn(preview["risk_level"], {"medium", "high"})

            approved_events = agent.approve(str(approval_events[0].details["approval_id"]))

            self.assertTrue(any(event.type == "checkpoint_created" and event.tool_name == "run_shell" for event in approved_events))
            shell_results = [event for event in approved_events if event.type == "tool_result" and event.tool_name == "run_shell"]
            self.assertEqual(len(shell_results), 1)
            self.assertIn("shell ok", shell_results[0].message or "")

    def test_run_shell_blocks_destructive_command_even_if_approved(self) -> None:
        """验证明显危险的 shell 命令不会在批准后执行。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_sample_repo(root)
            target = root / "README.md"

            agent = build_agent(root)
            events = agent.prompt("run shell command: Remove-Item README.md")
            approval_events = [event for event in events if event.type == "approval_required"]

            self.assertEqual(len(approval_events), 1)
            preview = approval_events[0].details["effect_preview"]
            self.assertEqual(preview["kind"], "run_shell")
            self.assertTrue(preview["blocked"])
            self.assertEqual(preview["risk_level"], "blocked")

            approved_events = agent.approve(str(approval_events[0].details["approval_id"]))
            pending = PendingApprovalStore(root / ".data" / "codemuse" / "approvals").load(str(approval_events[0].details["approval_id"]))

            self.assertEqual(pending.status, "stale")
            self.assertTrue(target.exists())
            self.assertTrue(any(event.type == "approval_stale" and event.tool_name == "run_shell" for event in approved_events))
            self.assertFalse(any(event.type == "tool_result" and event.tool_name == "run_shell" for event in approved_events))


def _write_sample_repo(root: Path) -> None:
    """为测试创建所需的本地文件或配置。"""
    (root / "README.md").write_text(
        "# Sample Agent\n\nA tiny coding agent that can save blueprint memory.\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text('[project]\nname = "sample-agent"\n', encoding="utf-8")
    for folder in ["src/sample/runtime", "src/sample/tools", "src/sample/storage"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "src/sample/runtime/runtime.py").write_text("class AgentRuntime:\n    pass\n", encoding="utf-8")
    (root / "src/sample/tools/registry.py").write_text("class ToolRegistry:\n    pass\n", encoding="utf-8")
    (root / "src/sample/storage/sessions.py").write_text("class SessionStore:\n    pass\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
