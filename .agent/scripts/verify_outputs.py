#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / ".agent" / "state"
LAST_VERIFICATION = STATE_DIR / "last-verification.json"
RUNTIME_STATE = STATE_DIR / "runtime-state.json"
DEFAULT_RUNTIME = {
    "task_id": "unknown-task",
    "failure_count": 0,
    "active_mode": "closed_loop",
    "last_commands": [],
    "last_verification": {"status": "not_run", "timestamp": None, "reason": None},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return dict(fallback)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def coerce_value(raw: str) -> object:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def normalize_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a deterministic verification result.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-type", choices=["exploratory", "deliverable"], default="deliverable")
    parser.add_argument("--level", choices=["light", "heavy"], required=True)
    parser.add_argument("--status", choices=["passed", "failed", "inconclusive"])
    parser.add_argument("--reason")
    parser.add_argument("--require-path", action="append", default=[])
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--source", action="append", default=[])
    args = parser.parse_args()

    checks: dict[str, object] = {}
    missing_paths: list[str] = []

    for item in args.require_path:
        candidate = normalize_path(item)
        key = f"path:{candidate.relative_to(REPO_ROOT).as_posix() if candidate.is_relative_to(REPO_ROOT) else str(candidate)}"
        exists = candidate.exists()
        checks[key] = exists
        if not exists:
            missing_paths.append(str(candidate))

    for item in args.check:
        if "=" not in item:
            parser.error(f"--check expects KEY=VALUE, got: {item}")
        key, raw_value = item.split("=", 1)
        checks[key] = coerce_value(raw_value)

    status = args.status
    if status is None:
        if missing_paths or any(value is False for value in checks.values()):
            status = "failed"
        elif checks:
            status = "passed"
        else:
            status = "inconclusive"

    reason = args.reason
    if not reason:
        if status == "failed" and missing_paths:
            reason = "missing required paths: " + ", ".join(missing_paths)
        elif status == "passed":
            reason = "deterministic verification checks passed"
        else:
            reason = "no deterministic checks were supplied"

    verification = {
        "task_id": args.task_id,
        "task_type": args.task_type,
        "level": args.level,
        "status": status,
        "timestamp": now_iso(),
        "checks": checks,
        "sources": args.source,
        "reason": reason,
    }
    write_json(LAST_VERIFICATION, verification)

    runtime = read_json(RUNTIME_STATE, DEFAULT_RUNTIME)
    runtime["task_id"] = args.task_id
    runtime["last_verification"] = {
        "status": verification["status"],
        "timestamp": verification["timestamp"],
        "reason": verification["reason"],
    }
    write_json(RUNTIME_STATE, runtime)

    print(json.dumps(verification, ensure_ascii=False))
    if status == "passed":
        return 0
    if status == "failed":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
