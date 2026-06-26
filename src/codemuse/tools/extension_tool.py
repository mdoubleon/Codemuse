"""Runtime tools for discovered CodeMuse extensions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codemuse.app.extensions_runtime import ExtensionRuntime
from codemuse.tools.base import BaseTool, ToolResult, ToolSpec


class RunExtensionTool(BaseTool):
    """Execute a safe manifest-driven extension action."""

    def __init__(self, workspace: Path, runtime: ExtensionRuntime) -> None:
        super().__init__(workspace)
        self.runtime = runtime

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_extension",
            description="Run a discovered extension through the safe manifest runtime.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "input": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["name"],
            },
            permission_domain="read",
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("run_extension requires an extension name.")
        result = self.runtime.run_extension(
            name=name,
            action=str(arguments.get("action") or "default"),
            input_text=str(arguments.get("input") or ""),
        )
        return ToolResult(
            tool_name=self.spec.name,
            content=result["content"],
            details=result,
        )


class DynamicExtensionTool(BaseTool):
    """A safe manifest-declared extension tool."""

    def __init__(self, workspace: Path, runtime: ExtensionRuntime, descriptor: dict[str, object]) -> None:
        super().__init__(workspace)
        self.runtime = runtime
        self.descriptor = descriptor

    @property
    def public_name(self) -> str:
        return "extension__" + _safe_name(str(self.descriptor["extension"])) + "__" + _safe_name(str(self.descriptor["name"]))

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.public_name,
            description=str(self.descriptor.get("description") or self.descriptor["name"]),
            parameters=dict(self.descriptor.get("input_schema") or {"type": "object", "properties": {"input": {"type": "string"}}}),
            permission_domain="read",
            side_effect=False,
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        input_text = str(arguments.get("input") or arguments.get("text") or arguments)
        result = self.runtime.run_extension(
            name=str(self.descriptor["extension"]),
            action=str(self.descriptor["name"]),
            input_text=input_text,
        )
        return ToolResult(tool_name=self.spec.name, content=result["content"], details=result)


def register_extension_tools(registry, workspace: Path, runtime: ExtensionRuntime) -> None:
    """Register extension runtime tools."""
    registry.register(RunExtensionTool(workspace, runtime), category="extension")
    for descriptor in runtime.dynamic_tools():
        registry.register(DynamicExtensionTool(workspace, runtime, descriptor), category="extension")


def _safe_name(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "tool"
