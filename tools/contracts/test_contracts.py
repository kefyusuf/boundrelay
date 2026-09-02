from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "fixtures/scenarios/support-triage.yaml"
FAKE = ROOT / "fixtures/fake-model/support-triage.yaml"
INVARIANTS = ROOT / "lessons/00-workflow-or-agent/invariants.yaml"


class CanonicalAssetTests(unittest.TestCase):
    def test_assets_define_matching_cases_and_routes(self) -> None:
        scenario = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
        fake = yaml.safe_load(FAKE.read_text(encoding="utf-8"))
        invariants = yaml.safe_load(INVARIANTS.read_text(encoding="utf-8"))

        self.assertEqual(scenario["schema_version"], "1.0")
        self.assertEqual(scenario["scenario_id"], "support-triage")
        self.assertEqual(scenario["routes"], ["billing", "technical", "general"])
        case_ids = {case["id"] for case in scenario["cases"]}
        self.assertEqual(case_ids, set(fake["responses"]))
        self.assertEqual(len(invariants["invariants"]), 10)


if __name__ == "__main__":
    unittest.main()
