import copy
import json
from pathlib import Path
import unittest

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CASES = {"code-billing-handoff", "model-technical-handoff", "model-low-confidence-fallback", "handoff-context-loss", "handoff-receiver-unavailable"}


def document(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def validator(path):
    return Draft202012Validator(json.loads((ROOT / path).read_text(encoding="utf-8")))


class M2Contracts(unittest.TestCase):
    def setUp(self):
        self.handoff = {"schema_version": "1.0", "handoff_id": "h-1", "sender": "support-router", "receiver": "billing-specialist", "sender_intent": {"route": "billing", "confidence": 0.8, "policy_outcome": "selected"}, "receiver_input": {"ticket_id": "TCK-1001", "request_text": "Invoice question"}}

    def test_exact_cases_and_isolated_failures(self):
        scenario = document("fixtures/scenarios/support-handoff.yaml")
        self.assertEqual({case["id"] for case in scenario["cases"]}, CASES)
        self.assertEqual(len(scenario["cases"]), 5)
        self.assertEqual(scenario["confidence_threshold"], 0.8)
        self.assertEqual(scenario["route_receivers"], {route: route + "-specialist" for route in ("billing", "technical", "general")})
        failures = document("fixtures/failures/support-handoff.yaml")["failures"]
        self.assertEqual(failures, {"handoff-context-loss": {"omit_receiver_input_fields": ["request_text"]}, "handoff-receiver-unavailable": {"unavailable_receivers": ["billing-specialist"]}})
        models = document("fixtures/fake-model/support-handoff.yaml")["decisions"]
        self.assertEqual(set(models), {case["id"] for case in scenario["cases"] if case["router_mode"] == "model"})
        for case in scenario["cases"]:
            if case["expected_status"] == "FAILED":
                self.assertEqual(case["failure_ref"], case["id"])
                self.assertIn(case["failure_ref"], failures)
            else:
                self.assertNotIn("failure_ref", case)

    def test_handoff_rejects_missing_and_excess_context(self):
        schema = validator("contracts/handoffs/support-handoff.schema.json")
        schema.validate(self.handoff)
        for key, value in [("ticket_id", "bad"), ("request_text", ""), ("prompt", "secret")]:
            bad = copy.deepcopy(self.handoff)
            bad["receiver_input"][key] = value
            self.assertFalse(schema.is_valid(bad))
        bad = copy.deepcopy(self.handoff)
        del bad["receiver_input"]["request_text"]
        self.assertFalse(schema.is_valid(bad))
        for boundary in (None, "sender_intent", "receiver_input"):
            bad = copy.deepcopy(self.handoff)
            (bad if boundary is None else bad[boundary])["extra"] = True
            self.assertFalse(schema.is_valid(bad))
        for key, value in [("sender", "other"), ("receiver", "unknown")]:
            bad = copy.deepcopy(self.handoff)
            bad[key] = value
            self.assertFalse(schema.is_valid(bad))

    def test_result_discriminates_domain_outcomes(self):
        schema = validator("contracts/results/handoff-result.schema.json")
        result = {"schema_version": "1.0", "run_id": "run-1", "scenario_id": "support-handoff", "case_id": "test", "router_mode": "code", "status": "SUCCEEDED", "proposed_route": "billing", "selected_route": "billing", "receiver": "billing-specialist", "fallback_applied": False, "specialist_invoked": True, "failure_code": None, "trace_path": "trace.jsonl"}
        schema.validate(result)
        for failure in ("HANDOFF_CONTEXT_INVALID", "HANDOFF_RECEIVER_UNAVAILABLE"):
            bad = {**result, "status": "FAILED", "failure_code": failure, "specialist_invoked": False}
            schema.validate(bad)
            self.assertFalse(schema.is_valid({**bad, "specialist_invoked": True}))
            self.assertFalse(schema.is_valid({**bad, "receiver": None}))
        invalid = {**result, "status": "FAILED", "failure_code": "INVALID_ROUTE_DECISION", "specialist_invoked": False, "proposed_route": None, "selected_route": None, "receiver": None}
        schema.validate(invalid)
        self.assertFalse(schema.is_valid({**invalid, "fallback_applied": True}))
        self.assertFalse(schema.is_valid({**result, "specialist_invoked": False}))

    def test_route_authority_and_invariants(self):
        route = validator("contracts/routing/route-decision.schema.json")
        route.validate({"route": "billing", "confidence": 0.8})
        self.assertFalse(route.is_valid({"route": "unknown", "confidence": 0.8}))
        self.assertFalse(route.is_valid({"route": "billing", "confidence": 0.8, "receiver": "billing-specialist"}))
        invariants = document("lessons/02-routing-handoff/invariants.yaml")
        self.assertEqual([item["id"] for item in invariants["invariants"]], [f"M2-I{i:02}" for i in range(1, 18)])


if __name__ == "__main__":
    unittest.main()
