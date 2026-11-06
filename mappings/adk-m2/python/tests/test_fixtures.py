"""Fixture loading: strict, checked-in artifacts only (RED first)."""
import unittest

from boundrelay_m2_adk import fixtures


class ScenarioProjectionTests(unittest.TestCase):
    def test_scenario_has_the_five_canonical_cases(self):
        scenario = fixtures.load_scenario_projection()
        self.assertEqual(scenario["schema_version"], "1.0")
        self.assertEqual(scenario["scenario_id"], "support-handoff")
        self.assertEqual(scenario["confidence_threshold"], 0.80)
        keys = tuple(case["id"] for case in scenario["cases"])
        self.assertEqual(keys, fixtures.PARITY_CASE_KEYS)

    def test_route_receivers_mapping_is_the_canonical_table(self):
        scenario = fixtures.load_scenario_projection()
        self.assertEqual(scenario["route_receivers"], fixtures.RECEIVER_BY_ROUTE)

    def test_case_modes_and_expectations_survive_parsing(self):
        scenario = fixtures.load_scenario_projection()
        by_id = {case["id"]: case for case in scenario["cases"]}
        self.assertEqual(by_id["code-billing-handoff"]["router_mode"], "code")
        self.assertEqual(by_id["code-billing-handoff"]["expected_status"],
                         "SUCCEEDED")
        self.assertEqual(
            by_id["model-low-confidence-fallback"]["expected_policy_outcome"],
            "fallback")
        self.assertEqual(
            by_id["handoff-context-loss"]["expected_failure_code"],
            "HANDOFF_CONTEXT_INVALID")
        self.assertEqual(
            by_id["handoff-receiver-unavailable"]["expected_failure_code"],
            "HANDOFF_RECEIVER_UNAVAILABLE")

    def test_attribution_tables_parse(self):
        tables = fixtures.load_attribution_projection()
        self.assertEqual(tables["latency_ms"]["classify"], 30)
        self.assertEqual(tables["latency_ms"]["receiver.general-specialist"], 12)
        self.assertEqual(tables["price_table"],
                         {"route": 0, "model_decision": 2, "handoff": 0})


class FakeModelProjectionTests(unittest.TestCase):
    def test_decisions_cover_exactly_the_model_cases(self):
        decisions = fixtures.load_fake_model_projection()
        self.assertEqual(set(decisions), {
            "model-technical-handoff", "model-low-confidence-fallback",
            "handoff-context-loss"})
        self.assertEqual(decisions["model-technical-handoff"],
                         {"route": "technical", "confidence": 0.92})
        self.assertEqual(decisions["model-low-confidence-fallback"],
                         {"route": "billing", "confidence": 0.54})


class FailuresProjectionTests(unittest.TestCase):
    def test_failures_cover_exactly_the_handoff_cases(self):
        failures = fixtures.load_failures_projection()
        self.assertEqual(set(failures),
                         {"handoff-context-loss",
                          "handoff-receiver-unavailable"})
        self.assertEqual(
            failures["handoff-context-loss"],
            {"omit_receiver_input_fields": ("request_text",)})
        self.assertEqual(
            failures["handoff-receiver-unavailable"],
            {"unavailable_receivers": ("billing-specialist",)})


class LoadCaseTests(unittest.TestCase):
    def test_code_case_carries_no_scripted_decision(self):
        case = fixtures.load_case("code-billing-handoff")
        self.assertEqual(case.case_id, "code-billing-handoff")
        self.assertEqual(case.router_mode, "code")
        self.assertIsNone(case.decision)
        self.assertIsNone(case.failure)
        self.assertEqual(case.ticket_id, "TCK-1001")

    def test_model_case_carries_its_scripted_decision(self):
        case = fixtures.load_case("model-technical-handoff")
        self.assertEqual(case.router_mode, "model")
        self.assertEqual(case.decision,
                         {"route": "technical", "confidence": 0.92})

    def test_failure_case_carries_its_failure_operator(self):
        case = fixtures.load_case("handoff-context-loss")
        self.assertEqual(case.failure,
                         {"omit_receiver_input_fields": ("request_text",)})
        case = fixtures.load_case("handoff-receiver-unavailable")
        self.assertEqual(case.failure,
                         {"unavailable_receivers": ("billing-specialist",)})

    def test_unknown_case_raises(self):
        with self.assertRaises(ValueError):
            fixtures.load_case("not-a-case")


class GoldenAndSchemaTests(unittest.TestCase):
    def test_every_parity_case_has_a_golden_projection(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                projection = fixtures.load_golden(key)
                self.assertEqual(projection["case_id"], key)
                self.assertIn("attribution", projection)

    def test_unknown_golden_raises(self):
        with self.assertRaises(ValueError):
            fixtures.load_golden("not-a-case")

    def test_contract_schemas_load(self):
        route_schema = fixtures.load_route_decision_schema()
        self.assertEqual(route_schema["title"], "M0 Route Decision")
        handoff_schema = fixtures.load_handoff_schema()
        self.assertEqual(handoff_schema["title"], "M2 Support Handoff")


if __name__ == "__main__":
    unittest.main()
