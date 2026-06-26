"""实现受审批保护的 shell 命令执行工具。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from codemuse.tools.base import BaseTool, ToolResult, ToolSpec
from codemuse.tools.effects import build_shell_effect_preview


class RunShellTool(BaseTool):
    """在 workspace 内执行 shell 命令的高风险工具，执行前必须经过审批。"""

    @property
    def spec(self) -> ToolSpec:
        """声明 run_shell 的命令、超时和输出限制，并要求审批。"""
        return ToolSpec(
            name="run_shell",
            description="Run a shell command inside the current workspace after approval.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "max_output_chars": {"type": "integer"},
                },
                "required": ["command"],
            },
            permission_domain="shell",
            requires_confirmation=True,
            sensitive=True,
            side_effect=True,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """审批通过后执行命令，并把输出、退出码和截断信息回填给 Runtime。"""
        preview = build_shell_effect_preview(self.workspace, arguments)
        if preview.get("blocked"):
            return ToolResult(
                tool_name=self.spec.name,
                content=f"Shell command blocked: {preview.get('reason')}",
                is_error=True,
                details={"effect_preview": preview},
            )

        command = str(preview["command"])
        timeout_seconds = int(preview["timeout_seconds"])
        max_output_chars = int(preview["max_output_chars"])
        try:
            completed = subprocess.run(
                _shell_invocation(command),
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            partial = _join_output(exc.stdout or "", exc.stderr or "")
            output, truncated = _truncate_output(partial, max_output_chars)
            return ToolResult(
                tool_name=self.spec.name,
                content=f"Shell command timed out after {timeout_seconds}s.\n{output}".strip(),
                is_error=True,
                details={
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                    "timed_out": True,
                    "output": output,
                    "output_truncated": truncated,
                },
            )

        output = _join_output(completed.stdout or "", completed.stderr or "")
        output, truncated = _truncate_output(output, max_output_chars)
        is_error = completed.returncode != 0
        status = f"Shell exited with code {completed.returncode}."
        content = f"{status}\n{output}".strip() if output else status
        return ToolResult(
            tool_name=self.spec.name,
            content=content,
            is_error=is_error,
            details={
                "command": command,
                "returncode": completed.returncode,
                "timeout_seconds": timeout_seconds,
                "output": output,
                "output_truncated": truncated,
                "risk_level": preview.get("risk_level"),
                "risk_reasons": preview.get("risk_reasons") or [],
            },
        )


def register_shell_tools(registry, workspace: Path) -> None:
    """把 shell 工具注册到 ToolRegistry。"""
    registry.register(RunShellTool(workspace))


def _shell_invocation(command: str) -> list[str]:
    """根据当前平台选择 shell 入口，并避免把命令直接交给 Python 的 shell=True。"""
    if Path.cwd().drive:
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["sh", "-lc", command]


def _join_output(stdout: str, stderr: str) -> str:
    """把 stdout 和 stderr 合并成工具结果文本。"""
    if stdout and stderr:
        return f"{stdout.rstrip()}\n{stderr.rstrip()}"
    return (stdout or stderr).strip()


def _truncate_output(output: str, max_chars: int) -> tuple[str, bool]:
    """限制 shell 输出长度，避免一次命令撑爆会话或前端。"""
    if len(output) <= max_chars:
        return output, False
    suffix = f"\n... output truncated, {len(output) - max_chars} characters omitted ..."
    return output[:max_chars] + suffix, True
