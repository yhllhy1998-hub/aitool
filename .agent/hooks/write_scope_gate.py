#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_TASK = REPO_ROOT / ".agent" / "state" / "active-task.yaml"
COMMON_DIR = REPO_ROOT / ".agent" / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from task_state import load_task_state
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
    return load_task_state(ACTIVE_TASK)


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
