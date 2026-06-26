"""Expose discovered workspace extensions as metadata capabilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json

from codemuse.capabilities.descriptor import CapabilityDescriptor
from codemuse.extensions.loader import ExtensionDescriptor, load_extensions


@dataclass
class ExtensionRuntime:
    workspace: Path
    _extensions: dict[str, ExtensionDescriptor] | None = field(default=None, init=False, repr=False)

    def available_extensions(self) -> dict[str, ExtensionDescriptor]:
        if self._extensions is None:
            self._extensions = load_extensions(self.workspace)
        return self._extensions

    def reload(self) -> None:
        self._extensions = None

    def run_extension(self, *, name: str, action: str = "default", input_text: str = "") -> dict[str, object]:
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

    def _manifest_payload(self, extension: ExtensionDescriptor) -> dict[str, object]:
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
        for item in payload.get("tools", []):
            if isinstance(item, dict) and item.get("name") == action and isinstance(item.get("response_template"), str):
                return str(item["response_template"])
        if isinstance(payload.get("response_template"), str):
            return str(payload["response_template"])
        return "Extension {name} handled action {action}: {input}"


@dataclass
class ExtensionCapabilityDiscoveryProvider:
    runtime: ExtensionRuntime

    def discover(self) -> list[CapabilityDescriptor]:
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
        self.runtime.reload()
