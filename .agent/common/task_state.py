#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if text == "":
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        return text[1:-1]
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _next_nonempty_line_starts_with_list(lines: list[str], start_index: int) -> bool:
    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.startswith("- ")
    return False


def _simple_yaml_load(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        container = stack[-1][1]

        if line.startswith("- "):
            if not isinstance(container, list):
                raise ValueError(f"invalid list placement: {raw_line}")
            container.append(_parse_scalar(line[2:]))
            continue

        if ":" not in line:
            raise ValueError(f"invalid mapping line: {raw_line}")

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value == "":
            next_container: Any = [] if _next_nonempty_line_starts_with_list(lines, index) else {}
            if not isinstance(container, dict):
                raise ValueError(f"invalid nested mapping placement: {raw_line}")
            container[key] = next_container
            stack.append((indent, next_container))
        else:
            if not isinstance(container, dict):
                raise ValueError(f"invalid scalar placement: {raw_line}")
            container[key] = _parse_scalar(value)

    return root


def load_task_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("task state root must be a mapping")
        return data
    except ModuleNotFoundError:
        return _simple_yaml_load(text)
