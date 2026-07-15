"""中转站条目的身份、排序和顺序维护业务逻辑。"""

from __future__ import annotations

import ntpath
from pathlib import Path
from typing import Iterable, Literal

from .models import StationEntry

SortMode = Literal["default", "custom"]
SORT_MODES = ("default", "custom")


def normalize_path_key(path: str | Path) -> str:
    """返回跨 Windows 大小写和尾斜杠稳定的路径身份键。"""
    candidate = Path(path).expanduser().resolve(strict=False)
    # ntpath.normpath gives Windows separators even when a POSIX temp path is
    # used by tests, while Path.resolve still supplies the required identity.
    return ntpath.normpath(str(candidate)).casefold()


def _entry_key(entry: StationEntry) -> str:
    return normalize_path_key(entry.path)


def _unique_entries(entries: Iterable[StationEntry]) -> list[StationEntry]:
    """按首次出现保留条目，避免旧数据中的重复路径泄漏到 UI。"""
    result: list[StationEntry] = []
    seen: set[str] = set()
    for entry in entries:
        try:
            key = _entry_key(entry)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if key not in seen:
            seen.add(key)
            result.append(entry)
    return result


def clean_custom_order(custom_order: Iterable[object] | None) -> list[str]:
    """清理 custom_order：仅保留合法字符串路径键，并去重保留首次。"""
    if custom_order is None or isinstance(custom_order, (str, bytes)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in custom_order:
        if not isinstance(item, str) or not item.strip():
            continue
        try:
            key = normalize_path_key(item)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def default_station_order(entries: Iterable[StationEntry]) -> list[StationEntry]:
    """按文件夹优先、名称排序，名称相同则按规范化路径稳定排序。"""
    unique = _unique_entries(entries)
    return sorted(
        unique,
        key=lambda entry: (
            entry.kind != "folder",
            entry.display_name.casefold(),
            _entry_key(entry),
        ),
    )


def custom_station_order(
    entries: Iterable[StationEntry], custom_order: Iterable[object] | None
) -> list[StationEntry]:
    """严格按 custom_order 排列，未列出的当前条目按输入顺序追加。"""
    unique = _unique_entries(entries)
    by_key = {_entry_key(entry): entry for entry in unique}
    result: list[StationEntry] = []
    used: set[str] = set()
    for key in clean_custom_order(custom_order):
        entry = by_key.get(key)
        if entry is not None:
            result.append(entry)
            used.add(key)
    result.extend(entry for entry in unique if _entry_key(entry) not in used)
    return result


def order_station_entries(
    entries: Iterable[StationEntry],
    sort_mode: str = "default",
    custom_order: Iterable[object] | None = None,
) -> list[StationEntry]:
    """根据受限的 sort_mode 返回中转站展示顺序。"""
    if sort_mode == "custom":
        return custom_station_order(entries, custom_order)
    return default_station_order(entries)


def complete_custom_order(
    entries: Iterable[StationEntry], custom_order: Iterable[object] | None
) -> list[str]:
    """清除旧键并追加当前未出现的条目键，返回可保存的顺序。"""
    unique = _unique_entries(entries)
    keys = [_entry_key(entry) for entry in unique]
    current = clean_custom_order(custom_order)
    present = set(keys)
    result = [key for key in current if key in present]
    result.extend(key for key in keys if key not in result)
    return result


def switch_sort_mode(
    entries: Iterable[StationEntry],
    current_mode: str,
    custom_order: Iterable[object] | None,
    target_mode: str,
) -> tuple[SortMode, list[str], list[StationEntry]]:
    """切换排序模式；切到 custom 时无历史顺序则从 default 展示顺序初始化。"""
    unique = _unique_entries(entries)
    if target_mode not in SORT_MODES:
        target_mode = "default"
    existing_order = clean_custom_order(custom_order)
    if target_mode == "custom" and not existing_order:
        existing_order = [_entry_key(entry) for entry in default_station_order(unique)]
    saved_order = complete_custom_order(unique, existing_order) if existing_order else []
    ordered = order_station_entries(unique, target_mode, saved_order)
    return target_mode, saved_order, ordered


def remove_station_entry(
    entries: Iterable[StationEntry],
    path: str | Path,
    custom_order: Iterable[object] | None,
) -> tuple[list[StationEntry], list[str]]:
    """删除条目并同步删除其身份键；再次收集同一路径会自然追加到末尾。"""
    target = normalize_path_key(path)
    remaining = [entry for entry in entries if _entry_key(entry) != target]
    return remaining, [key for key in clean_custom_order(custom_order) if key != target]
