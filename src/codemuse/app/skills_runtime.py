"""提供应用装配中 skills runtime 相关实现。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import time

from codemuse.capabilities.descriptor import CapabilityDescriptor
from codemuse.domain.messages import ChatMessage
from codemuse.skills.loader import SkillDescriptor, load_skills


@dataclass
class SkillRuntime:
    """管理 SkillRuntime 运行时的状态、发现和执行入口。"""
    workspace: Path
    _skills: dict[str, SkillDescriptor] | None = field(default=None, init=False, repr=False)
    _manual_active: list[str] = field(default_factory=list, init=False, repr=False)
    _last_active: list[str] = field(default_factory=list, init=False, repr=False)

    def available_skills(self) -> dict[str, SkillDescriptor]:
        """处理 availableskills。"""
        if self._skills is None:
            self._skills = load_skills(self.workspace)
        return self._skills

    def reload(self) -> None:
        """处理 reload。"""
        self._skills = None
        self._manual_active = []
        self._last_active = []

    def use_skill(self, name: str) -> SkillDescriptor:
        skills = self.available_skills()
        if name not in skills:
            raise ValueError(f"Unknown skill: {name}")
        if name not in self._manual_active:
            self._manual_active.append(name)
        return skills[name]

    def match_skills(self, text: str, *, limit: int = 2) -> list[SkillDescriptor]:
        """Match explicit names first, then meaningful description-term overlap."""
        clean = text.strip().lower()
        if not clean:
            return []
        skills = [item for item in self.available_skills().values() if item.status == "loaded"]
        explicit = [item for item in skills if any(value in clean for value in {item.name.lower(), item.name.lower().replace("-", " "), item.name.lower().replace("_", " ")})]
        if explicit:
            return sorted(explicit, key=lambda item: clean.find(item.name.lower()))[:limit]
        terms = _match_terms(clean)
        candidates: list[tuple[int, SkillDescriptor]] = []
        for item in skills:
            description_terms = _match_terms(item.description)
            score = len(terms & description_terms)
            if score:
                candidates.append((score, item))
        return [item for _score, item in sorted(candidates, key=lambda pair: (-pair[0], pair[1].name))[:limit]]

    def transform_context(self, state, messages: list[ChatMessage]) -> list[ChatMessage]:
        latest = next((item.text_content() for item in reversed(state.messages) if item.role == "user"), "")
        matched = self.match_skills(latest)
        names = list(dict.fromkeys([*self._manual_active, *[item.name for item in matched]]))
        self._last_active = names
        if not names:
            return messages
        sections = ["Active CodeMuse skills for this turn:"]
        for name in names:
            skill = self.available_skills().get(name)
            if skill is None or skill.status != "loaded":
                continue
            body = skill.path.read_text(encoding="utf-8-sig")[:8000]
            sections.extend([f"\n[Skill: {skill.name}]", body])
        injected = ChatMessage.text("system", "\n".join(sections))
        injected.metadata.update({"skills": names, "generated_at": time.time()})
        return [injected, *messages]

    def active_skills(self) -> list[str]:
        return list(self._last_active)

    def run_skill(self, *, name: str, task: str = "", max_chars: int = 4000) -> dict[str, object]:
        """运行Skill。"""
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
    """提供 SkillCapabilityDiscoveryProvider 的能力发现或适配逻辑。"""
    runtime: SkillRuntime

    def discover(self) -> list[CapabilityDescriptor]:
        """发现应用装配。"""
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
        """处理 reload。"""
        self.runtime.reload()


def _match_terms(text: str) -> set[str]:
    stopwords = {"the", "and", "for", "with", "this", "that", "from", "into", "using", "build"}
    return {item for item in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(item) >= 3 and item not in stopwords}
