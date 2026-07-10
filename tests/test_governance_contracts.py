from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_GOVERNANCE = REPO_ROOT / ".agent" / "state" / "skill-governance.json"
PRACTICE_REGISTRY = REPO_ROOT / ".agent" / "state" / "practice-registry.json"


class GovernanceContractTests(unittest.TestCase):
    def test_skill_governance_declares_primary_sources_and_agent_workflow_limits(self) -> None:
        payload = json.loads(SKILL_GOVERNANCE.read_text(encoding="utf-8"))
        self.assertIn("primary_governance_sources", payload)
        self.assertGreaterEqual(len(payload["primary_governance_sources"]), 3)
        self.assertIn("skills", payload)
        self.assertIn("agent-workflow", payload["skills"])
        agent_workflow = payload["skills"]["agent-workflow"]
        self.assertIn("allowed_when", agent_workflow)
        self.assertIn("not_for", agent_workflow)
        self.assertTrue(any("替代主控手册" == item for item in agent_workflow["not_for"]))

    def test_practice_registry_declares_aitool_role_and_governance_contract(self) -> None:
        payload = json.loads(PRACTICE_REGISTRY.read_text(encoding="utf-8"))
        self.assertIn("projects", payload)
        projects = payload["projects"]
        self.assertTrue(any(item["id"] == "aitool" for item in projects))
        aitool = next(item for item in projects if item["id"] == "aitool")
        self.assertEqual(aitool["role"], "正式项目 / harness实践项目")
        self.assertIn("governance_contract", aitool)
        self.assertGreaterEqual(len(aitool["governance_contract"]), 2)


if __name__ == "__main__":
    unittest.main()
