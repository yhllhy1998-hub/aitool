from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TASK = REPO_ROOT / ".agent" / "state" / "active-task.yaml"
RUNTIME_STATE = REPO_ROOT / ".agent" / "state" / "runtime-state.json"
LAST_VERIFICATION = REPO_ROOT / ".agent" / "state" / "last-verification.json"
DANGEROUS_CMD = REPO_ROOT / ".agent" / "hooks" / "dangerous_cmd.py"
WRITE_SCOPE_GATE = REPO_ROOT / ".agent" / "hooks" / "write_scope_gate.py"
VERIFY_OUTPUTS = REPO_ROOT / ".agent" / "scripts" / "verify_outputs.py"


def run_python(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class Phase1RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_active_task = ACTIVE_TASK.read_text(encoding="utf-8")
        self.original_runtime_state = RUNTIME_STATE.read_text(encoding="utf-8")
        self.original_last_verification = LAST_VERIFICATION.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        ACTIVE_TASK.write_text(self.original_active_task, encoding="utf-8")
        RUNTIME_STATE.write_text(self.original_runtime_state, encoding="utf-8")
        LAST_VERIFICATION.write_text(self.original_last_verification, encoding="utf-8")

    def test_dangerous_command_classifier_blocks_git_reset_hard(self) -> None:
        result = run_python(DANGEROUS_CMD, "git", "reset", "--hard")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dangerous"])
        self.assertEqual(payload["label"], "git-reset-hard")

    def test_write_scope_gate_allows_executor_inside_allow_write(self) -> None:
        ACTIVE_TASK.write_text(
            "\n".join(
                [
                    "task_id: allow-docs",
                    "current_table: harness_template",
                    "stage: test",
                    "status: in_progress",
                    "task_type: exploratory",
                    "actor: executor",
                    "allow_write:",
                    "  - docs/",
                    "next_step: keep testing",
                    "override:",
                    "  enabled: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = run_python(WRITE_SCOPE_GATE, "docs/project-architecture.md")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["allowed"])

    def test_write_scope_gate_blocks_protected_assets_for_executor(self) -> None:
        ACTIVE_TASK.write_text(
            "\n".join(
                [
                    "task_id: block-assets",
                    "current_table: harness_template",
                    "stage: test",
                    "status: in_progress",
                    "task_type: exploratory",
                    "actor: executor",
                    "allow_write:",
                    "  - assets/",
                    "next_step: keep testing",
                    "override:",
                    "  enabled: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = run_python(WRITE_SCOPE_GATE, "assets/sample.xlsx")
        payload = json.loads(result.stdout)
        self.assertFalse(payload["allowed"])

    def test_write_scope_gate_allows_master_controller_path_scope(self) -> None:
        ACTIVE_TASK.write_text(
            "\n".join(
                [
                    "task_id: master-controller-bypass",
                    "current_table: harness_template",
                    "stage: test",
                    "status: in_progress",
                    "task_type: deliverable",
                    "actor: master-controller",
                    "allow_write:",
                    "  - docs/",
                    "next_step: keep testing",
                    "override:",
                    "  enabled: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = run_python(WRITE_SCOPE_GATE, "assets/source-of-truth.xlsx")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["allowed"])

    def test_verify_outputs_fails_when_required_path_is_missing(self) -> None:
        result = run_python(
            VERIFY_OUTPUTS,
            "--task-id",
            "verify-missing",
            "--level",
            "light",
            "--require-path",
            "docs/does-not-exist.md",
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")


if __name__ == "__main__":
    unittest.main()
