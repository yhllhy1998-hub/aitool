#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_TASK = REPO_ROOT / ".agent" / "state" / "active-task.yaml"


def _simple_yaml_load(text: str) -> dict:
    """Minimal YAML parser for active-task.yaml structure.

    Handles: simple key:value, lists with '- item', nested dicts,
    multi-line strings with '>', and empty lines.
    Does NOT handle: anchors, aliases, flow style, complex block scalars.
    """
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # detect top-level key: value
        colon = stripped.find(":")
        if colon == -1:
            i += 1
            continue
        key = stripped[:colon].strip()
        after_colon = stripped[colon + 1:].strip()
        # multi-line string with > or |
        if after_colon in (">", "|"):
            value = _consume_block_scalar(lines, i + 1)
            result[key] = value
            i += 1
            while i < len(lines) and lines[i].strip().startswith(("  ", "\t")):
                i += 1
            continue
        if after_colon:
            # simple scalar value
            result[key] = _coerce_value(after_colon)
            i += 1
        else:
            # key with no immediate value: look ahead for list or nested dict
            i, value = _consume_nested(lines, i + 1)
            result[key] = value
            continue
    return result


def _coerce_value(raw: str) -> object:
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.lower() == "null" or raw == "~":
        return None
    # try int then float
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    # strip quotes
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def _consume_block_scalar(lines: list[str], start: int) -> str:
    segments: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            if segments:
                segments.append("")
            i += 1
            continue
        if line.startswith(("  ", "\t")):
            segments.append(line.strip())
            i += 1
        else:
            break
    return " ".join(segments)


def _consume_nested(lines: list[str], start: int) -> tuple[int, object]:
    """Consume either a list of '- item' lines or nested key:value dict."""
    i = start
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("#")):
        i += 1
    if i >= len(lines):
        return i, []

    first_line = lines[i]
    first_stripped = first_line.strip()
    if first_stripped.startswith("- "):
        # list
        items: list = []
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue
            if stripped.startswith("- "):
                items.append(_coerce_value(stripped[2:].strip()))
                i += 1
            else:
                break
        return i, items
    else:
        # nested dict
        nested: dict = {}
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue
            colon = stripped.find(":")
            if colon == -1:
                break
            key = stripped[:colon].strip()
            after = stripped[colon + 1:].strip()
            if after in (">", "|"):
                nested[key] = _consume_block_scalar(lines, i + 1)
                i += 1
                while i < len(lines) and lines[i].strip().startswith(("  ", "\t")):
                    i += 1
            elif after:
                nested[key] = _coerce_value(after)
                i += 1
            else:
                # nested key with no immediate value
                i, sub_value = _consume_nested(lines, i + 1)
                nested[key] = sub_value
        return i, nested
PROTECTED_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "assets/",
    "baseline/",
    "fixtures/",
    "samples/",
    "input/",
    "inputs/",
    "templates/",
    "source-of-truth/",
)
OVERRIDE_PERMISSION_PREFIXES: Final[dict[str, tuple[str, ...]]] = {
    "write_docs": ("docs/",),
    "write_agent": (".agent/",),
    "write_src": ("src/",),
    "write_tests": ("tests/",),
    "write_assets": PROTECTED_PATH_PREFIXES,
}


def normalize_rel(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()
    return path.replace("\\", "/").lstrip("./")


def load_active_task() -> dict:
    raw = ACTIVE_TASK.read_text(encoding="utf-8")
    return _simple_yaml_load(raw)


def matches_scope(target: str, allowed: str) -> bool:
    scope = normalize_rel(allowed)
    if not scope:
        return False
    if scope.endswith("/"):
        return target.startswith(scope)
    return target == scope or target.startswith(scope + "/")


def is_protected_path(target: str) -> bool:
    return any(target.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def override_permissions(state: dict) -> list[str]:
    override = state.get("override") or {}
    if not override.get("enabled"):
        return []
    permissions = override.get("permissions") or []
    return [str(item) for item in permissions]


def override_allows(target: str, state: dict) -> bool:
    for permission in override_permissions(state):
        for prefix in OVERRIDE_PERMISSION_PREFIXES.get(permission, ()):
            if target.startswith(prefix):
                return True
    return False


def is_allowed_path(target_path: str, state: dict) -> dict[str, object]:
    actor = str(state.get("actor", "executor")).lower()
    rel_target = normalize_rel(target_path)
    if not rel_target:
        return {"allowed": False, "reason": "target path is empty"}

    if actor == "master-controller":
        return {
            "allowed": True,
            "reason": "master-controller retains boundary-definition authority for path scope",
        }

    if is_protected_path(rel_target):
        if override_allows(rel_target, state):
            return {"allowed": True, "reason": "protected path allowed by explicit override"}
        return {"allowed": False, "reason": "protected paths are denied unless explicitly overridden"}

    allow_write = state.get("allow_write") or []
    if any(matches_scope(rel_target, str(item)) for item in allow_write):
        return {"allowed": True, "reason": "path is inside allow_write"}

    if override_allows(rel_target, state):
        return {"allowed": True, "reason": "path allowed by explicit override"}

    return {"allowed": False, "reason": "target path is outside allow_write"}


def main() -> int:
    if len(sys.argv) < 2:
        sys.stdout.write(json.dumps({"allowed": False, "reason": "missing target path"}, ensure_ascii=False))
        return 1
    result = is_allowed_path(sys.argv[1], load_active_task())
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
