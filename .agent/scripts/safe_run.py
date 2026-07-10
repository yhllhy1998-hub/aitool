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
COMMON_DIR = REPO_ROOT / ".agent" / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from task_state import load_task_state

DEFAULT_RUNTIME = {
    "task_id": "unknown-task",
    "failure_count": 0,
    "active_mode": "closed_loop",
    "last_commands": [],
    "last_verification": {"status": "not_run", "timestamp": None, "reason": None},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_active_task() -> dict:
    return load_task_state(ACTIVE_TASK)


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
