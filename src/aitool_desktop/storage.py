from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import CustomModule, MODULE_TYPES, StationEntry, StationState
from .station_ordering import clean_custom_order, complete_custom_order, normalize_path_key, order_station_entries


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class StationStorage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._loaded_state = StationState()

    @property
    def current_state(self) -> StationState:
        """返回当前已加载状态的副本，避免调用方修改内部状态。"""
        state = self._loaded_state
        return StationState(list(state.entries), state.sort_mode, list(state.custom_order), state.updated_at)

    def load(self) -> list[StationEntry]:
        state = self.load_state()
        return order_station_entries(state.entries, state.sort_mode, state.custom_order)

    def save(self, entries: list[StationEntry]) -> None:
        """兼容旧调用，保留当前已加载的排序模式和 custom_order 保存 v2 文件。"""
        self.save_state(
            entries,
            sort_mode=self._loaded_state.sort_mode,
        )

    def _reset_loaded_state(self) -> StationState:
        self._loaded_state = StationState()
        return self._loaded_state

    def load_state(self) -> StationState:
        """读取 v1/v2 状态；坏数据和失效条目安全降级为空或 default。"""
        try:
            if not self.path.exists():
                return self._reset_loaded_state()
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            return self._reset_loaded_state()

        if not isinstance(payload, dict):
            return self._reset_loaded_state()

        schema_version = payload.get("schema_version", 1)
        if type(schema_version) is not int or schema_version not in (1, 2):
            return self._reset_loaded_state()

        entries = self._load_entries(payload.get("entries"))
        updated_at = payload.get("updated_at", "")
        if not isinstance(updated_at, str):
            updated_at = ""

        if schema_version == 1:
            # v1 had no persisted sorting state.  In particular, do not infer
            # a custom order from the input order of entries.
            state = StationState(entries, "default", [], updated_at)
        else:
            sort_mode = payload.get("sort_mode", "default")
            if sort_mode not in ("default", "custom"):
                sort_mode = "default"
            custom_order = payload.get("custom_order", [])
            if not isinstance(custom_order, list):
                custom_order = []
            # An explicit empty order is meaningful: it is a deliberate
            # cleared custom order, not a request to manufacture one from the
            # current entries.  A non-empty order is still normalized so stale
            # keys are removed and newly present entries are appended.
            saved_order = complete_custom_order(entries, custom_order) if custom_order else []
            state = StationState(entries, sort_mode, saved_order, updated_at)

        # Loading never writes the legacy file. Invalid/stale order is merely
        # normalized in memory and is persisted on the next successful save.
        self._loaded_state = state
        return state

    @staticmethod
    def _load_entries(raw_entries: object) -> list[StationEntry]:
        if not isinstance(raw_entries, list):
            return []
        entries: list[StationEntry] = []
        seen: set[str] = set()
        for item in raw_entries:
            try:
                entry = StationEntry.from_dict(item)
                if not entry.path.strip():
                    continue
                path = Path(entry.path)
                key = normalize_path_key(path)
                if not path.exists() or key in seen:
                    continue
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                continue
            seen.add(key)
            entries.append(entry)
        return entries

    def save_state(
        self,
        entries: list[StationEntry] | StationState,
        sort_mode: str = "default",
        custom_order: list[object] | None = None,
    ) -> None:
        """以同目录临时文件加 replace 原子保存中转站 v2 状态。"""
        if isinstance(entries, StationState):
            state = entries
            entries = state.entries
            sort_mode = state.sort_mode
            custom_order = state.custom_order
        if sort_mode not in ("default", "custom"):
            sort_mode = "default"
        if custom_order is None:
            custom_order = self._loaded_state.custom_order
        # None means "reuse the loaded order"; an explicit empty list means
        # clear it.  Keep an empty loaded order empty as well, rather than
        # manufacturing an order merely because entries are being saved.
        saved_order = complete_custom_order(entries, custom_order) if custom_order else []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "updated_at": now_iso(),
            "sort_mode": sort_mode,
            "custom_order": saved_order,
            "entries": [item.to_dict() for item in entries],
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temp_name: str | None = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
            temp_name = None
            self._loaded_state = StationState(list(entries), sort_mode, saved_order, payload["updated_at"])
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


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
