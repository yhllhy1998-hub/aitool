#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FILES = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "docs" / "master-controller-handbook.md",
    REPO_ROOT / "docs" / "project-architecture.md",
    REPO_ROOT / "docs" / "version-plan.md",
    REPO_ROOT / ".agent" / "state" / "active-task.yaml",
    REPO_ROOT / ".agent" / "state" / "runtime-state.json",
    REPO_ROOT / ".agent" / "state" / "last-verification.json",
)
ACTIVE_TASK = REPO_ROOT / ".agent" / "state" / "active-task.yaml"
RUNTIME_STATE = REPO_ROOT / ".agent" / "state" / "runtime-state.json"
LAST_VERIFICATION = REPO_ROOT / ".agent" / "state" / "last-verification.json"


@dataclass
class CheckResult:
    key: str
    passed: bool
    detail: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def check_required_files(checks: list[CheckResult]) -> None:
    for path in REQUIRED_FILES:
        exists = path.exists()
        checks.append(CheckResult(
            key=f"required-file:{rel(path)}",
            passed=exists,
            detail="存在" if exists else "缺失",
        ))


def check_task_id_consistency(checks: list[CheckResult]) -> None:
    try:
        import yaml
    except ImportError:
        checks.append(CheckResult("task-id-consistency", False, "PyYAML 未安装"))
        return

    try:
        at = yaml.safe_load(ACTIVE_TASK.read_text(encoding="utf-8"))
        rs = json.loads(RUNTIME_STATE.read_text(encoding="utf-8"))
        lv = json.loads(LAST_VERIFICATION.read_text(encoding="utf-8"))
    except Exception as exc:
        checks.append(CheckResult("task-id-consistency", False, f"读取失败: {exc}"))
        return

    at_id = at.get("task_id") if isinstance(at, dict) else None
    rs_id = rs.get("task_id") if isinstance(rs, dict) else None
    lv_id = lv.get("task_id") if isinstance(lv, dict) else None

    match = at_id and at_id == rs_id == lv_id
    checks.append(CheckResult(
        "task-id-consistency",
        passed=bool(match),
        detail=f"active-task={at_id} runtime-state={rs_id} last-verification={lv_id}",
    ))


def main() -> int:
    checks: list[CheckResult] = []
    check_required_files(checks)
    check_task_id_consistency(checks)

    failed = [c for c in checks if not c.passed]
    result = {
        "status": "failed" if failed else "passed",
        "timestamp": now_iso(),
        "summary": {"total": len(checks), "failed": len(failed)},
        "checks": [asdict(c) for c in checks],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
