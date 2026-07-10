from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_GOVERNANCE = REPO_ROOT / ".agent" / "scripts" / "check_governance.py"
PRACTICE_REGISTRY = REPO_ROOT / ".agent" / "state" / "practice-registry.json"


def run_python(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class GovernanceRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_practice_registry = PRACTICE_REGISTRY.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        PRACTICE_REGISTRY.write_text(self.original_practice_registry, encoding="utf-8")

    def test_check_governance_passes_on_current_repo_contract(self) -> None:
        result = run_python(CHECK_GOVERNANCE)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed")

    def test_check_governance_fails_when_positioning_doc_is_missing(self) -> None:
        payload = json.loads(self.original_practice_registry)
        payload["projects"][0]["positioning_docs"] = ["docs/does-not-exist.md"]
        PRACTICE_REGISTRY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = run_python(CHECK_GOVERNANCE)
        self.assertEqual(result.returncode, 1)
        checked = json.loads(result.stdout)
        self.assertEqual(checked["status"], "failed")
        self.assertTrue(any(item["key"].endswith("docs/does-not-exist.md") and item["passed"] is False for item in checked["checks"]))

    def test_check_governance_can_validate_registered_paths(self) -> None:
        payload = json.loads(self.original_practice_registry)
        payload["projects"][0]["path"] = str(REPO_ROOT)
        PRACTICE_REGISTRY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = run_python(CHECK_GOVERNANCE, "--check-registered-paths")
        self.assertEqual(result.returncode, 0)
        checked = json.loads(result.stdout)
        self.assertTrue(checked["summary"]["checked_registered_paths"])


if __name__ == "__main__":
    unittest.main()
