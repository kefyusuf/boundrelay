import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "fixtures/scenarios/support-handoff.yaml"
FAKE_MODEL = ROOT / "fixtures/fake-model/support-handoff.yaml"
FAILURES = ROOT / "fixtures/failures/support-handoff.yaml"
INVARIANTS = ROOT / "lessons/02-routing-handoff/invariants.yaml"
ROUTE_SCHEMA = ROOT / "contracts/routing/route-decision.schema.json"
HANDOFF_SCHEMA = ROOT / "contracts/handoffs/support-handoff.schema.json"
RESULT_SCHEMA = ROOT / "contracts/results/handoff-result.schema.json"
EVENT_SCHEMA = ROOT / "contracts/events/run-event.schema.json"

EXPECTED_CASES = {
    "code-billing-handoff",
    "model-technical-handoff",
    "model-low-confidence-fallback",
    "handoff-context-loss",
    "handoff-receiver-unavailable",
}
EXPECTED_MODEL_CASES = {
    "model-technical-handoff",
    "model-low-confidence-fallback",
    "handoff-context-loss",
}
EXPECTED_FAILURE_CASES = {
    "handoff-context-loss",
    "handoff-receiver-unavailable",
}
ROUTE_RECEIVERS = {
    "billing": "billing-specialist",
    "technical": "technical-specialist",
    "general": "general-specialist",
}


def load_yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected YAML object: {path}")
    return value


def load_schema(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected JSON object: {path}")
    return value


def schema_errors(path: Path, value: object):
    return list(Draft202012Validator(load_schema(path)).iter_errors(value))


class M2ContractTests(unittest.TestCase):
    def test_scenario_defines_exact_five_cases_threshold_and_receiver_mapping(self) -> None:
        scenario = load_yaml(SCENARIO)
        self.assertEqual(scenario["schema_version"], "1.0")
        self.assertEqual(scenario["scenario_id"], "support-handoff")
        self.assertEqual(scenario["confidence_threshold"], 0.80)
        self.assertEqual(scenario["route_receivers"], ROUTE_RECEIVERS)
        cases = {case["id"]: case for case in scenario["cases"]}
        self.assertEqual(set(cases), EXPECTED_CASES)
        self.assertEqual(cases["model-low-confidence-fallback"]["expected_proposed_route"], "billing")
        self.assertEqual(cases["model-low-confidence-fallback"]["expected_confidence"], 0.54)
        self.assertEqual(cases["model-low-confidence-fallback"]["expected_selected_route"], "general")
        self.assertEqual(cases["model-low-confidence-fallback"]["expected_receiver"], "general-specialist")
        self.assertIs(cases["model-low-confidence-fallback"]["expected_fallback_applied"], True)
        self.assertEqual(cases["handoff-context-loss"]["failure_ref"], "handoff-context-loss")
        self.assertEqual(cases["handoff-receiver-unavailable"]["failure_ref"], "handoff-receiver-unavailable")

    def test_model_and_failure_fixtures_are_exact_and_isolated(self) -> None:
        model = load_yaml(FAKE_MODEL)
        failures = load_yaml(FAILURES)
        self.assertEqual(model["schema_version"], "1.0")
        self.assertEqual(model["scenario_id"], "support-handoff")
        self.assertEqual(set(model["decisions"]), EXPECTED_MODEL_CASES)
        self.assertEqual(model["decisions"]["model-technical-handoff"]["return"], {"route": "technical", "confidence": 0.92})
        self.assertEqual(model["decisions"]["model-low-confidence-fallback"]["return"], {"route": "billing", "confidence": 0.54})
        self.assertEqual(failures["schema_version"], "1.0")
        self.assertEqual(failures["scenario_id"], "support-handoff")
        self.assertEqual(set(failures["failures"]), EXPECTED_FAILURE_CASES)
        self.assertEqual(failures["failures"]["handoff-context-loss"], {"omit_receiver_input_fields": ["request_text"]})
        self.assertEqual(failures["failures"]["handoff-receiver-unavailable"], {"unavailable_receivers": ["billing-specialist"]})
        self.assertNotIn("code-billing-handoff", failures["failures"])

    def test_existing_route_schema_remains_m0_authority(self) -> None:
        route_schema = load_schema(ROUTE_SCHEMA)
        self.assertEqual(route_schema["required"], ["route", "confidence"])
        self.assertIs(route_schema["additionalProperties"], False)
        self.assertEqual(route_schema["properties"]["route"]["enum"], ["billing", "technical", "general"])
        self.assertEqual(set(route_schema["properties"]), {"route", "confidence"})
        self.assertEqual(schema_errors(ROUTE_SCHEMA, {"route": "billing", "confidence": 0.80}), [])
        self.assertNotEqual(schema_errors(ROUTE_SCHEMA, {"route": "unknown", "confidence": 0.80}), [])
        self.assertNotEqual(schema_errors(ROUTE_SCHEMA, {"route": "billing", "confidence": 0.80, "receiver": "billing-specialist"}), [])

    def test_handoff_schema_enforces_minimum_context_and_nested_boundaries(self) -> None:
        valid = {
            "schema_version": "1.0",
            "handoff_id": "handoff-1",
            "sender": "support-router",
            "receiver": "billing-specialist",
            "sender_intent": {"route": "billing", "confidence": 1.0, "policy_outcome": "selected"},
            "receiver_input": {"ticket_id": "TCK-1001", "request_text": "I was charged twice."},
        }
        self.assertEqual(schema_errors(HANDOFF_SCHEMA, valid), [])
        missing = json.loads(json.dumps(valid))
        del missing["receiver_input"]["request_text"]
        self.assertNotEqual(schema_errors(HANDOFF_SCHEMA, missing), [])
        extra = json.loads(json.dumps(valid))
        extra["receiver_input"]["model_prompt"] = "must not cross handoff boundary"
        self.assertNotEqual(schema_errors(HANDOFF_SCHEMA, extra), [])
        bad_ticket = json.loads(json.dumps(valid))
        bad_ticket["receiver_input"]["ticket_id"] = "1001"
        self.assertNotEqual(schema_errors(HANDOFF_SCHEMA, bad_ticket), [])
        bad_sender = dict(valid, sender="other-router")
        self.assertNotEqual(schema_errors(HANDOFF_SCHEMA, bad_sender), [])
        bad_receiver = dict(valid, receiver="unknown-specialist")
        self.assertNotEqual(schema_errors(HANDOFF_SCHEMA, bad_receiver), [])
        extra_intent = json.loads(json.dumps(valid))
        extra_intent["sender_intent"]["selected_route"] = "billing"
        self.assertNotEqual(schema_errors(HANDOFF_SCHEMA, extra_intent), [])

    def test_result_schema_encodes_success_handoff_failure_and_invalid_route(self) -> None:
        success = {
            "schema_version": "1.0",
            "run_id": "run-1",
            "scenario_id": "support-handoff",
            "case_id": "code-billing-handoff",
            "router_mode": "code",
            "status": "SUCCEEDED",
            "proposed_route": "billing",
            "selected_route": "billing",
            "receiver": "billing-specialist",
            "fallback_applied": False,
            "specialist_invoked": True,
            "failure_code": None,
            "trace_path": ".boundrelay/m2/code.jsonl",
        }
        context_failure = dict(success)
        context_failure.update({
            "case_id": "handoff-context-loss",
            "router_mode": "model",
            "status": "FAILED",
            "specialist_invoked": False,
            "failure_code": "HANDOFF_CONTEXT_INVALID",
        })
        unavailable = dict(success)
        unavailable.update({
            "case_id": "handoff-receiver-unavailable",
            "status": "FAILED",
            "specialist_invoked": False,
            "failure_code": "HANDOFF_RECEIVER_UNAVAILABLE",
        })
        invalid_route = dict(success)
        invalid_route.update({
            "case_id": "invalid-route-unit",
            "router_mode": "model",
            "status": "FAILED",
            "proposed_route": None,
            "selected_route": None,
            "receiver": None,
            "fallback_applied": False,
            "specialist_invoked": False,
            "failure_code": "INVALID_ROUTE_DECISION",
        })
        for value in (success, context_failure, unavailable, invalid_route):
            self.assertEqual(schema_errors(RESULT_SCHEMA, value), [], value)
        invalid_success = dict(success, specialist_invoked=False)
        self.assertNotEqual(schema_errors(RESULT_SCHEMA, invalid_success), [])
        invalid_handoff_failure = dict(context_failure, receiver=None)
        self.assertNotEqual(schema_errors(RESULT_SCHEMA, invalid_handoff_failure), [])
        invalid_route_with_receiver = dict(invalid_route, receiver="billing-specialist")
        self.assertNotEqual(schema_errors(RESULT_SCHEMA, invalid_route_with_receiver), [])

    def test_event_schema_preserves_m0_m1_and_adds_only_handoff_family(self) -> None:
        event_schema = load_schema(EVENT_SCHEMA)
        event_types = event_schema["properties"]["type"]["enum"]
        for existing in ("route.selected", "route.rejected", "tool.requested", "budget.exceeded"):
            self.assertIn(existing, event_types)
        for handoff_type in ("handoff.requested", "handoff.accepted", "handoff.rejected"):
            self.assertIn(handoff_type, event_types)
        self.assertEqual(len([x for x in event_types if x.startswith("handoff.")]), 3)
        base = {
            "schema_version": "1.0",
            "event_id": "evt-1",
            "run_id": "run-1",
            "sequence": 1,
            "timestamp": "2026-09-30T00:00:00Z",
            "source": "python",
            "data": {},
        }
        self.assertEqual(schema_errors(EVENT_SCHEMA, dict(base, type="handoff.requested")), [])
        self.assertEqual(schema_errors(EVENT_SCHEMA, dict(base, type="tool.requested")), [])

    def test_invariants_are_exact_m2_i01_through_m2_i17(self) -> None:
        invariants = load_yaml(INVARIANTS)
        self.assertEqual(invariants["schema_version"], "1.0")
        self.assertEqual(invariants["scenario_id"], "support-handoff")
        ids = [item["id"] for item in invariants["invariants"]]
        self.assertEqual(ids, [f"M2-I{i:02d}" for i in range(1, 18)])

    def test_schema_declarations_are_valid_draft_2020_12(self) -> None:
        for path in (ROUTE_SCHEMA, HANDOFF_SCHEMA, RESULT_SCHEMA, EVENT_SCHEMA):
            Draft202012Validator.check_schema(load_schema(path))


if __name__ == "__main__":
    unittest.main()
