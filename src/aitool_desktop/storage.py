from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import CustomModule, MODULE_TYPES, StationEntry


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class StationStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[StationEntry]:
        if not self.path.exists():
            return []

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        entries: list[StationEntry] = []
        for item in payload.get("entries", []):
            try:
                entry = StationEntry.from_dict(item)
            except (KeyError, TypeError):
                continue
            if Path(entry.path).exists():
                entries.append(entry)
        return entries

    def save(self, entries: list[StationEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": now_iso(),
            "entries": [item.to_dict() for item in entries],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ModuleStorage:
    """自定义模块的持久化存储。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[CustomModule]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        modules: list[CustomModule] = []
        for item in payload.get("modules", []):
            try:
                module = CustomModule.from_dict(item)
            except (KeyError, TypeError):
                continue
            if module.module_type in MODULE_TYPES:
                modules.append(module)
        return modules

    def save(self, modules: list[CustomModule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": now_iso(),
            "modules": [m.to_dict() for m in modules],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def generate_id() -> str:
        return uuid.uuid4().hex[:12]
