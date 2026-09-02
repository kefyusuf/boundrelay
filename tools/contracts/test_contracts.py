import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "fixtures/scenarios/support-triage.yaml"
FAKE = ROOT / "fixtures/fake-model/support-triage.yaml"
INVARIANTS = ROOT / "lessons/00-workflow-or-agent/invariants.yaml"
ROUTE_SCHEMA = ROOT / "contracts/routing/route-decision.schema.json"
EVENT_SCHEMA = ROOT / "contracts/events/run-event.schema.json"
RESULT_SCHEMA = ROOT / "contracts/results/run-result.schema.json"


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

    def test_schemas_accept_valid_and_reject_invalid_boundaries(self) -> None:
        route_schema = json.loads(ROUTE_SCHEMA.read_text(encoding="utf-8"))
        event_schema = json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))
        result_schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
        route_validator = Draft202012Validator(route_schema)
        event_validator = Draft202012Validator(event_schema)
        result_validator = Draft202012Validator(result_schema)

        self.assertFalse(list(route_validator.iter_errors({"route": "billing", "confidence": 0.9})))
        self.assertTrue(list(route_validator.iter_errors({"route": "unknown", "confidence": 0.9})))
        self.assertFalse(list(event_validator.iter_errors({
            "schema_version": "1.0",
            "event_id": "evt-1",
            "run_id": "run-1",
            "sequence": 1,
            "type": "run.created",
            "timestamp": "2026-09-02T00:00:00Z",
            "source": "python",
            "data": {},
        })))
        self.assertFalse(list(result_validator.iter_errors({
            "schema_version": "1.0", "run_id": "run-1", "scenario_id": "support-triage",
            "case_id": "billing-duplicate-charge", "mode": "deterministic", "status": "SUCCEEDED",
            "selected_route": "billing", "specialist_invoked": True, "failure_code": None,
            "trace_path": ".boundrelay/m0/trace.jsonl",
        })))
        self.assertTrue(list(result_validator.iter_errors({
            "schema_version": "1.0", "run_id": "run-1", "scenario_id": "support-triage",
            "case_id": "invalid-model-route", "mode": "model", "status": "FAILED",
            "selected_route": "billing", "specialist_invoked": True, "failure_code": None,
            "trace_path": ".boundrelay/m0/trace.jsonl",
        })))

    def test_m0_workflow_uses_documented_gate_and_current_actions(self) -> None:
        workflow = (ROOT / ".github/workflows/m0.yml").read_text(encoding="utf-8")
        for expected in (
            "actions/checkout@v7",
            "actions/setup-node@v7",
            "actions/setup-python@v7",
            "actions/upload-artifact@v7",
            "python scripts/verify_m0.py",
            ".boundrelay/m0/",
        ):
            self.assertIn(expected, workflow)

    def test_schema_declarations_and_scenario_expectations_are_valid(self) -> None:
        for schema_path in (ROUTE_SCHEMA, EVENT_SCHEMA, RESULT_SCHEMA):
            Draft202012Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))

        scenario = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
        for case in scenario["cases"]:
            expectation_count = int("expected_route" in case) + int("expected_failure_code" in case)
            self.assertEqual(expectation_count, 1, case["id"])


if __name__ == "__main__":
    unittest.main()
