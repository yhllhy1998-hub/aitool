#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / ".agent" / "state"
LOG_DIR = REPO_ROOT / ".agent" / "logs"
ACTIVE_TASK = STATE_DIR / "active-task.yaml"
RUNTIME_STATE = STATE_DIR / "runtime-state.json"
DANGEROUS_HOOK = REPO_ROOT / ".agent" / "hooks" / "dangerous_cmd.py"
SCOPE_HOOK = REPO_ROOT / ".agent" / "hooks" / "write_scope_gate.py"
SAFE_RUN_LOG = LOG_DIR / "safe-run.log"
DEFAULT_RUNTIME = {
    "task_id": "unknown-task",
    "failure_count": 0,
    "active_mode": "closed_loop",
    "last_commands": [],
    "last_verification": {"status": "not_run", "timestamp": None, "reason": None},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Minimal YAML parser for active-task.yaml (copied from write_scope_gate.py)
# ---------------------------------------------------------------------------

def _coerce_value(raw: str) -> object:
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.lower() == "null" or raw == "~":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
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
    i = start
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("#")):
        i += 1
    if i >= len(lines):
        return i, []

    first_stripped = lines[i].strip()
    if first_stripped.startswith("- "):
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
                i, sub_value = _consume_nested(lines, i + 1)
                nested[key] = sub_value
        return i, nested


def _simple_yaml_load(text: str) -> dict:
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        colon = stripped.find(":")
        if colon == -1:
            i += 1
            continue
        key = stripped[:colon].strip()
        after_colon = stripped[colon + 1:].strip()
        if after_colon in (">", "|"):
            result[key] = _consume_block_scalar(lines, i + 1)
            i += 1
            while i < len(lines) and lines[i].strip().startswith(("  ", "\t")):
                i += 1
            continue
        if after_colon:
            result[key] = _coerce_value(after_colon)
            i += 1
        else:
            i, value = _consume_nested(lines, i + 1)
            result[key] = value
            continue
    return result


def read_active_task() -> dict:
    if not ACTIVE_TASK.exists():
        return {}
    raw = ACTIVE_TASK.read_text(encoding="utf-8")
    return _simple_yaml_load(raw)


def read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return dict(fallback)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_log(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with SAFE_RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_json_script(script: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = (result.stdout or result.stderr).strip() or "{}"
    return json.loads(payload)


def update_runtime(task_state: dict, command: str, exit_code: int, status: str) -> None:
    runtime = read_json(RUNTIME_STATE, DEFAULT_RUNTIME)
    runtime["task_id"] = task_state.get("task_id") or runtime.get("task_id") or DEFAULT_RUNTIME["task_id"]
    commands = runtime.get("last_commands") or []
    commands.append(
        {
            "command": command,
            "timestamp": now_iso(),
            "exit_code": exit_code,
            "status": status,
        }
    )
    runtime["last_commands"] = commands[-10:]
    if exit_code != 0:
        runtime["failure_count"] = int(runtime.get("failure_count", 0)) + 1
    write_json(RUNTIME_STATE, runtime)


def parse_cli(argv: list[str]) -> tuple[list[str], list[str]]:
    write_paths: list[str] = []
    args = list(argv)
    while args[:1] == ["--write-path"]:
        if len(args) < 2:
            raise ValueError("--write-path requires a value")
        write_paths.append(args[1])
        args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        raise ValueError("no command provided")
    return write_paths, args


def main() -> int:
    try:
        write_paths, command_args = parse_cli(sys.argv[1:])
    except ValueError as exc:
        print(f"Usage: safe_run.py [--write-path REL_PATH ...] -- <command...>\nError: {exc}", file=sys.stderr)
        return 2

    task_state = read_active_task()
    actor = str(task_state.get("actor", "executor")).lower()
    command_text = subprocess.list2cmdline(command_args)

    dangerous = run_json_script(DANGEROUS_HOOK, command_text)
    if dangerous.get("dangerous"):
        append_log(
            {
                "timestamp": now_iso(),
                "task_id": task_state.get("task_id"),
                "actor": actor,
                "command": command_text,
                "status": "blocked",
                "reason": dangerous.get("reason"),
            }
        )
        update_runtime(task_state, command_text, exit_code=1, status="blocked")
        print(dangerous.get("reason", "command blocked"), file=sys.stderr)
        return 1

    for write_path in write_paths:
        scope = run_json_script(SCOPE_HOOK, write_path)
        if not scope.get("allowed"):
            append_log(
                {
                    "timestamp": now_iso(),
                    "task_id": task_state.get("task_id"),
                    "actor": actor,
                    "command": command_text,
                    "status": "blocked",
                    "reason": scope.get("reason"),
                    "write_path": write_path,
                }
            )
            update_runtime(task_state, command_text, exit_code=1, status="blocked")
            print(scope.get("reason", "path blocked"), file=sys.stderr)
            return 1

    proc = subprocess.run(command_args, cwd=REPO_ROOT, check=False)
    append_log(
        {
            "timestamp": now_iso(),
            "task_id": task_state.get("task_id"),
            "actor": actor,
            "command": command_text,
            "status": "ran",
            "exit_code": proc.returncode,
            "write_paths": write_paths,
        }
    )
    update_runtime(task_state, command_text, exit_code=proc.returncode, status="ran")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
