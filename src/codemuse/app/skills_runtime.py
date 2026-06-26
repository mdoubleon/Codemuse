"""Expose discovered workspace skills as metadata capabilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codemuse.capabilities.descriptor import CapabilityDescriptor
from codemuse.skills.loader import SkillDescriptor, load_skills


@dataclass
class SkillRuntime:
    workspace: Path
    _skills: dict[str, SkillDescriptor] | None = field(default=None, init=False, repr=False)

    def available_skills(self) -> dict[str, SkillDescriptor]:
        if self._skills is None:
            self._skills = load_skills(self.workspace)
        return self._skills

    def reload(self) -> None:
        self._skills = None

    def run_skill(self, *, name: str, task: str = "", max_chars: int = 4000) -> dict[str, object]:
        skills = self.available_skills()
        if name not in skills:
            raise ValueError(f"Unknown skill: {name}")
        skill = skills[name]
        if skill.status != "loaded":
            raise RuntimeError(f"Skill is not loaded: {name}: {skill.error}")
        body = skill.path.read_text(encoding="utf-8-sig")
        content = body[:max_chars]
        truncated = len(body) > max_chars
        if truncated:
            content += f"\n\n[truncated {len(body) - max_chars} characters]"
        rendered = "\n".join(
            [
                f"# Skill: {skill.name}",
                "",
                f"- description: {skill.description}",
                f"- source: {skill.source}",
                f"- task: {task or 'not specified'}",
                "",
                "## Instructions",
                content,
            ]
        )
        return {
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "path": str(skill.path),
            "task": task,
            "truncated": truncated,
            "content": rendered,
        }


@dataclass
class SkillCapabilityDiscoveryProvider:
    runtime: SkillRuntime

    def discover(self) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for skill in self.runtime.available_skills().values():
            descriptors.append(
                CapabilityDescriptor(
                    kind="skill",
                    name=skill.name,
                    description=skill.description,
                    source=f"{skill.source}:{skill.path}",
                    status=skill.status,
                    risk_level="low",
                    cost_hint="low",
                    metadata={
                        "path": str(skill.path),
                        "source": skill.source,
                        "precedence": skill.precedence,
                        "discovery_mode": skill.discovery_mode,
                        "error": skill.error,
                        "runtime_tool": "run_skill",
                    },
                )
            )
        return descriptors

    def reload(self) -> None:
        self.runtime.reload()
