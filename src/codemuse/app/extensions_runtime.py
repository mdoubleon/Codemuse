"""提供应用装配中 extensions runtime 相关实现。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json

from codemuse.capabilities.descriptor import CapabilityDescriptor
from codemuse.extensions.loader import ExtensionDescriptor, load_extensions
from codemuse.domain.messages import ChatMessage


@dataclass
class ExtensionRuntime:
    """管理 ExtensionRuntime 运行时的状态、发现和执行入口。"""
    workspace: Path
    _extensions: dict[str, ExtensionDescriptor] | None = field(default=None, init=False, repr=False)

    def available_extensions(self) -> dict[str, ExtensionDescriptor]:
        """处理 availableextensions。"""
        if self._extensions is None:
            self._extensions = load_extensions(self.workspace)
        return self._extensions

    def reload(self) -> None:
        """处理 reload。"""
        self._extensions = None

    def run_extension(self, *, name: str, action: str = "default", input_text: str = "") -> dict[str, object]:
        """运行扩展。"""
        extensions = self.available_extensions()
        if name not in extensions:
            raise ValueError(f"Unknown extension: {name}")
        extension = extensions[name]
        if extension.status != "loaded":
            raise RuntimeError(f"Extension is not loaded: {name}: {extension.error}")
        manifest = extension.path / "EXTENSION.json"
        if not manifest.exists():
            manifest = extension.path / "extension.json"
        payload = self._manifest_payload(extension)
        response_template = self._response_template(payload, action)
        content = response_template.format(
            name=extension.name,
            action=action,
            input=input_text,
            version=extension.version,
        )
        return {
            "name": extension.name,
            "description": extension.description,
            "version": extension.version,
            "provides": list(extension.provides),
            "entrypoint": extension.entrypoint or "",
            "action": action,
            "input": input_text,
            "content": content,
            "execution": "manifest_runtime",
        }

    def dynamic_tools(self) -> list[dict[str, object]]:
        """处理 动态tools。"""
        tools: list[dict[str, object]] = []
        for extension in self.available_extensions().values():
            if extension.status != "loaded":
                continue
            payload = self._manifest_payload(extension)
            for item in payload.get("tools", []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                tools.append(
                    {
                        "extension": extension.name,
                        "name": name,
                        "description": str(item.get("description") or name),
                        "input_schema": dict(item.get("input_schema") or {"type": "object", "properties": {"input": {"type": "string"}}}),
                        "response_template": str(item.get("response_template") or ""),
                    }
                )
        return tools

    def install_hooks(self, hooks) -> list[str]:
        """Install declarative manifest hooks without importing extension code."""
        installed: list[str] = []
        for extension in self.available_extensions().values():
            if extension.status != "loaded":
                continue
            payload = self._manifest_payload(extension)
            hook_config = payload.get("hooks")
            if not isinstance(hook_config, dict):
                continue
            context_template = hook_config.get("context_template")
            if isinstance(context_template, str) and context_template.strip():
                def inject(_state, messages, template=context_template, item=extension):
                    text = template.format(name=item.name, version=item.version)
                    message = ChatMessage.text("system", text)
                    message.metadata["extension"] = item.name
                    return [message, *messages]
                hooks.add_transform_context_hook(extension.name, "extension", inject)
                installed.append(f"{extension.name}:context_built")
            lifecycle_events = hook_config.get("lifecycle_events")
            if isinstance(lifecycle_events, list):
                allowed = {str(value) for value in lifecycle_events if str(value).strip()}
                if allowed:
                    def observe(event, selected=allowed, item=extension):
                        if event.type in selected:
                            event.details.setdefault("extension_hooks", []).append(item.name)
                    hooks.lifecycle_event_hooks.append(observe)
                    installed.append(f"{extension.name}:lifecycle")
        return installed

    def _manifest_payload(self, extension: ExtensionDescriptor) -> dict[str, object]:
        """处理 清单载荷。"""
        manifest = extension.path / "EXTENSION.json"
        if not manifest.exists():
            manifest = extension.path / "extension.json"
        if not manifest.exists():
            return {}
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return dict(payload) if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _response_template(self, payload: dict[str, object], action: str) -> str:
        """处理 响应template。"""
        for item in payload.get("tools", []):
            if isinstance(item, dict) and item.get("name") == action and isinstance(item.get("response_template"), str):
                return str(item["response_template"])
        if isinstance(payload.get("response_template"), str):
            return str(payload["response_template"])
        return "Extension {name} handled action {action}: {input}"


@dataclass
class ExtensionCapabilityDiscoveryProvider:
    """提供 ExtensionCapabilityDiscoveryProvider 的能力发现或适配逻辑。"""
    runtime: ExtensionRuntime

    def discover(self) -> list[CapabilityDescriptor]:
        """发现应用装配。"""
        descriptors: list[CapabilityDescriptor] = []
        for extension in self.runtime.available_extensions().values():
            descriptors.append(
                CapabilityDescriptor(
                    kind="extension",
                    name=extension.name,
                    description=extension.description,
                    source=f"{extension.source}:{extension.path}",
                    status=extension.status,
                    risk_level="medium",
                    cost_hint="medium",
                    metadata={
                        "path": str(extension.path),
                        "source": extension.source,
                        "precedence": extension.precedence,
                        "entrypoint": extension.entrypoint,
                        "provides": list(extension.provides),
                        "version": extension.version,
                        "error": extension.error,
                        "execution": "manifest_runtime",
                        "runtime_tool": "run_extension",
                    },
                )
            )
        return descriptors

    def reload(self) -> None:
        """处理 reload。"""
        self.runtime.reload()
