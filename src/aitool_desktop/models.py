from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class StationEntry:
    path: str
    kind: str
    display_name: str

    @classmethod
    def from_path(cls, path: Path) -> "StationEntry":
        return cls(
            path=str(path),
            kind="folder" if path.is_dir() else "file",
            display_name=path.name or str(path),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "StationEntry":
        return cls(
            path=str(payload["path"]),
            kind=str(payload["kind"]),
            display_name=str(payload["display_name"]),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "kind": self.kind,
            "display_name": self.display_name,
        }


@dataclass(slots=True)
class ActionReview:
    action: str
    status: str
    mode: str
    summary: str
    details: list[str]


MODULE_TYPES = ("folder-copy", "launch-bat", "update-svn", "commit-svn", "open-web", "app-launch")


@dataclass(slots=True)
class CustomModule:
    """用户自定义模块定义。"""
    module_id: str
    name: str
    module_type: str
    params: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict) -> "CustomModule":
        return cls(
            module_id=str(payload["module_id"]),
            name=str(payload["name"]),
            module_type=str(payload["module_type"]),
            params=dict(payload.get("params", {})),
        )

    def to_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "module_type": self.module_type,
            "params": dict(self.params),
        }
