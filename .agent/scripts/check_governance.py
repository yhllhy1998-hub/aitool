#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_GOVERNANCE = REPO_ROOT / ".agent" / "state" / "skill-governance.json"
PRACTICE_REGISTRY = REPO_ROOT / ".agent" / "state" / "practice-registry.json"
REQUIRED_GOVERNANCE_FILES = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "docs" / "master-controller-handbook.md",
    REPO_ROOT / "docs" / "project-architecture.md",
    REPO_ROOT / "docs" / "version-plan.md",
    REPO_ROOT / "docs" / "project-positioning.md",
    REPO_ROOT / "docs" / "delivery-acceptance.md",
    REPO_ROOT / "docs" / "self-evolution-architecture.md",
    SKILL_GOVERNANCE,
    PRACTICE_REGISTRY,
)


@dataclass
class CheckResult:
    key: str
    passed: bool
    detail: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def add_check(checks: list[CheckResult], key: str, passed: bool, detail: str) -> None:
    checks.append(CheckResult(key=key, passed=passed, detail=detail))


def rel_label(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path, checks: list[CheckResult], key_prefix: str) -> dict | None:
    if not path.exists():
        add_check(checks, f"{key_prefix}:exists", False, f"{rel_label(path)} 缺失")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add_check(checks, f"{key_prefix}:json", False, f"{rel_label(path)} 不是合法 JSON: {exc}")
        return None
    add_check(checks, f"{key_prefix}:json", True, f"{rel_label(path)} JSON 结构有效")
    return payload


def check_required_files(checks: list[CheckResult]) -> None:
    for path in REQUIRED_GOVERNANCE_FILES:
        exists = path.exists()
        add_check(
            checks,
            f"required-file:{rel_label(path)}",
            exists,
            "存在" if exists else "缺少必需治理文件",
        )


def is_non_empty_list(value: object) -> bool:
    return isinstance(value, list) and bool(value)


def check_skill_governance(payload: dict | None, checks: list[CheckResult]) -> None:
    if not isinstance(payload, dict):
        add_check(checks, "skill-governance:payload", False, "技能治理文件根节点必须是对象")
        return

    primary_sources = payload.get("primary_governance_sources")
    add_check(
        checks,
        "skill-governance:primary-sources",
        is_non_empty_list(primary_sources),
        "primary_governance_sources 必须是非空列表",
    )
    if isinstance(primary_sources, list):
        for source in primary_sources:
            candidate = REPO_ROOT / str(source)
            add_check(
                checks,
                f"skill-governance:source:{source}",
                candidate.exists(),
                "治理源存在" if candidate.exists() else "声明的治理源文件不存在",
            )

    policy = payload.get("external_skill_policy")
    add_check(
        checks,
        "skill-governance:external-policy",
        isinstance(policy, dict),
        "external_skill_policy 必须是对象",
    )
    if isinstance(policy, dict):
        add_check(
            checks,
            "skill-governance:default-role",
            bool(policy.get("default_role")),
            "external_skill_policy.default_role 必须定义",
        )
        add_check(
            checks,
            "skill-governance:before-use-checks",
            is_non_empty_list(policy.get("before_use_checks")),
            "external_skill_policy.before_use_checks 必须是非空列表",
        )

    skills = payload.get("skills")
    add_check(
        checks,
        "skill-governance:skills",
        isinstance(skills, dict) and bool(skills),
        "skills 必须是非空对象",
    )
    if isinstance(skills, dict):
        for skill_name, config in skills.items():
            prefix = f"skill-governance:skill:{skill_name}"
            add_check(
                checks,
                f"{prefix}:config",
                isinstance(config, dict),
                "技能配置必须是对象",
            )
            if not isinstance(config, dict):
                continue
            add_check(
                checks,
                f"{prefix}:role",
                bool(config.get("role")),
                "技能 role 必须定义",
            )
            add_check(
                checks,
                f"{prefix}:allowed-when",
                is_non_empty_list(config.get("allowed_when")),
                "allowed_when 必须是非空列表",
            )
            add_check(
                checks,
                f"{prefix}:not-for",
                is_non_empty_list(config.get("not_for")),
                "not_for 必须是非空列表",
            )


def check_practice_registry(payload: dict | None, checks: list[CheckResult], check_paths: bool) -> None:
    if not isinstance(payload, dict):
        add_check(checks, "practice-registry:payload", False, "项目实践登记文件根节点必须是对象")
        return

    projects = payload.get("projects")
    add_check(
        checks,
        "practice-registry:projects",
        is_non_empty_list(projects),
        "projects 必须是非空列表",
    )
    if not isinstance(projects, list):
        return

    for project in projects:
        project_id = str(project.get("id") or "<missing-id>") if isinstance(project, dict) else "<invalid-project>"
        prefix = f"practice-registry:{project_id}"
        add_check(
            checks,
            f"{prefix}:config",
            isinstance(project, dict),
            "项目条目必须是对象",
        )
        if not isinstance(project, dict):
            continue

        add_check(checks, f"{prefix}:path", bool(project.get("path")), "项目路径必须定义")
        add_check(checks, f"{prefix}:role", bool(project.get("role")), "项目角色必须定义")
        add_check(
            checks,
            f"{prefix}:primary-phases",
            is_non_empty_list(project.get("primary_phases")),
            "primary_phases 必须是非空列表",
        )
        add_check(
            checks,
            f"{prefix}:use-for",
            is_non_empty_list(project.get("use_for")),
            "use_for 必须是非空列表",
        )
        add_check(
            checks,
            f"{prefix}:not-for",
            is_non_empty_list(project.get("not_for")),
            "not_for 必须是非空列表",
        )
        positioning_docs = project.get("positioning_docs")
        add_check(
            checks,
            f"{prefix}:positioning-docs",
            is_non_empty_list(positioning_docs),
            "positioning_docs 必须是非空列表",
        )
        if isinstance(positioning_docs, list):
            for doc in positioning_docs:
                candidate = REPO_ROOT / str(doc)
                add_check(
                    checks,
                    f"{prefix}:positioning-doc:{doc}",
                    candidate.exists(),
                    "定位文档存在" if candidate.exists() else "声明的定位文档不存在",
                )
        add_check(
            checks,
            f"{prefix}:governance-contract",
            is_non_empty_list(project.get("governance_contract")),
            "governance_contract 必须是非空列表",
        )

        if check_paths and project.get("path"):
            project_path = Path(str(project["path"]))
            add_check(
                checks,
                f"{prefix}:path-exists",
                project_path.exists(),
                "登记路径存在" if project_path.exists() else "登记路径不存在",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 AiTool 的治理约束与项目定位文件。")
    parser.add_argument(
        "--check-registered-paths",
        action="store_true",
        help="额外校验 practice-registry.json 中登记的路径当前是否存在。",
    )
    args = parser.parse_args()

    checks: list[CheckResult] = []
    check_required_files(checks)

    skill_payload = read_json(SKILL_GOVERNANCE, checks, "skill-governance")
    practice_payload = read_json(PRACTICE_REGISTRY, checks, "practice-registry")

    check_skill_governance(skill_payload, checks)
    check_practice_registry(practice_payload, checks, check_paths=args.check_registered_paths)

    failed = [item for item in checks if not item.passed]
    payload = {
        "status": "failed" if failed else "passed",
        "timestamp": now_iso(),
        "summary": {
            "total": len(checks),
            "failed": len(failed),
            "checked_registered_paths": args.check_registered_paths,
        },
        "checks": [asdict(item) for item in checks],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
