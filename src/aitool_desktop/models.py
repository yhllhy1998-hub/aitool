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
        if not isinstance(payload, dict):
            raise TypeError("station entry must be an object")
        if not all(isinstance(payload.get(key), str) for key in ("path", "kind", "display_name")):
            raise TypeError("station entry fields must be strings")
        return cls(
            path=payload["path"],
            kind=payload["kind"],
            display_name=payload["display_name"],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "kind": self.kind,
            "display_name": self.display_name,
        }


@dataclass(slots=True)
class StationState:
    """中转站持久化状态（v2）。"""

    entries: list[StationEntry] = field(default_factory=list)
    sort_mode: str = "default"
    custom_order: list[str] = field(default_factory=list)
    updated_at: str = ""


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
