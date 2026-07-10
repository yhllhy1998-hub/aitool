#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class DangerousPattern:
    label: str
    reason: str
    pattern: re.Pattern[str]


DANGEROUS_PATTERNS: Final[tuple[DangerousPattern, ...]] = (
    DangerousPattern(
        label="rm-rf",
        reason="rm -rf recursively deletes files and is considered destructive.",
        pattern=re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\b"),
    ),
    DangerousPattern(
        label="powershell-remove-item",
        reason="Remove-Item -Recurse -Force can delete repository content irreversibly.",
        pattern=re.compile(r"\bremove-item\b(?=.*\b-recurse\b)(?=.*\b-force\b)", re.IGNORECASE),
    ),
    DangerousPattern(
        label="cmd-del-recursive",
        reason="del /s /q recursively deletes files and is considered destructive.",
        pattern=re.compile(r"\bdel\b(?=.*(?:\s|^)/s\b)(?=.*(?:\s|^)/q\b)", re.IGNORECASE),
    ),
    DangerousPattern(
        label="cmd-rmdir-recursive",
        reason="rmdir /s /q recursively deletes directories and is considered destructive.",
        pattern=re.compile(r"\brmdir\b(?=.*(?:\s|^)/s\b)(?=.*(?:\s|^)/q\b)", re.IGNORECASE),
    ),
    DangerousPattern(
        label="git-reset-hard",
        reason="git reset --hard discards local changes.",
        pattern=re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    ),
    DangerousPattern(
        label="git-clean-force",
        reason="git clean -fd removes untracked files and directories.",
        pattern=re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f[a-zA-Z]*d[a-zA-Z]*\b", re.IGNORECASE),
    ),
    DangerousPattern(
        label="git-push-force",
        reason="git push --force rewrites remote history.",
        pattern=re.compile(r"\bgit\s+push\b.*(?:-f\b|--force(?:-with-lease)?\b)", re.IGNORECASE),
    ),
)


def classify_command(command: str) -> dict[str, object]:
    normalized = command.strip()
    for item in DANGEROUS_PATTERNS:
        if item.pattern.search(normalized):
            return {"dangerous": True, "label": item.label, "reason": item.reason}
    return {"dangerous": False}


def main() -> int:
    if len(sys.argv) > 1:
        command = " ".join(sys.argv[1:])
    else:
        command = sys.stdin.read().strip()
    sys.stdout.write(json.dumps(classify_command(command), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
