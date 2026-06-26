"""Data models for repository import planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RepoImportPlan:
    source: str
    source_type: str
    repo_id: str
    requires_network: bool
    import_ready: bool
    local_path: str = ""
    owner: str = ""
    name: str = ""
    branch: str = ""
    clone_url: str = ""
    recommended_path: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "repo_id": self.repo_id,
            "requires_network": self.requires_network,
            "import_ready": self.import_ready,
            "local_path": self.local_path,
            "owner": self.owner,
            "name": self.name,
            "branch": self.branch,
            "clone_url": self.clone_url,
            "recommended_path": self.recommended_path,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoImportPlan":
        return cls(
            source=str(data["source"]),
            source_type=str(data["source_type"]),
            repo_id=str(data["repo_id"]),
            requires_network=bool(data["requires_network"]),
            import_ready=bool(data["import_ready"]),
            local_path=str(data.get("local_path") or ""),
            owner=str(data.get("owner") or ""),
            name=str(data.get("name") or ""),
            branch=str(data.get("branch") or ""),
            clone_url=str(data.get("clone_url") or ""),
            recommended_path=str(data.get("recommended_path") or ""),
            notes=list(data.get("notes") or []),
        )
