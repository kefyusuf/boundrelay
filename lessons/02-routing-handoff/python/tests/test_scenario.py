from pathlib import Path
import tempfile
import unittest

from boundrelay_m2.scenario import (
    find_scenario_case,
    load_failure_fixtures,
    load_scenario,
)
from boundrelay_m2.scripted_router import ScriptedRouteError, ScriptedRouteProvider


class ScenarioTests(unittest.IsolatedAsyncioTestCase):
    def test_loads_canonical_fallback_case_without_coercion(self) -> None:
        scenario = load_scenario()
        case = find_scenario_case(scenario, "model-low-confidence-fallback")
        self.assertEqual(scenario.scenario_id, "support-handoff")
        self.assertEqual(scenario.confidence_threshold, 0.80)
        self.assertEqual(case.router_mode, "model")
        self.assertEqual(case.expected_proposed_route, "billing")
        self.assertEqual(case.expected_confidence, 0.54)
        self.assertEqual(case.expected_selected_route, "general")
        self.assertEqual(case.expected_receiver, "general-specialist")
        self.assertTrue(case.expected_fallback_applied)

    def test_loads_exactly_two_isolated_failure_records(self) -> None:
        failures = load_failure_fixtures()
        self.assertEqual(
            set(failures),
            {"handoff-context-loss", "handoff-receiver-unavailable"},
        )
        self.assertNotIn("code-billing-handoff", failures)

    def test_rejects_malformed_confidence_threshold_instead_of_coercing(self) -> None:
        content = '''schema_version: "1.0"
scenario_id: support-handoff
confidence_threshold: "0.80"
route_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}
cases: []
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "confidence_threshold"):
                load_scenario(path)

    def test_rejects_numeric_threshold_other_than_exact_080(self) -> None:
        content = '''schema_version: "1.0"
scenario_id: support-handoff
confidence_threshold: 0.70
route_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}
cases: []
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "confidence_threshold must be 0.80"):
                load_scenario(path)

    def test_rejects_unknown_failure_ref_and_extra_failure_operator(self) -> None:
        scenario_content = '''schema_version: "1.0"
scenario_id: support-handoff
confidence_threshold: 0.80
route_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}
cases:
  - id: bad
    ticket_id: TCK-1001
    request: bad
    router_mode: code
    expected_status: FAILED
    expected_proposed_route: billing
    expected_confidence: 1.0
    expected_selected_route: billing
    expected_receiver: billing-specialist
    expected_policy_outcome: selected
    expected_fallback_applied: false
    expected_specialist_invoked: false
    expected_failure_code: HANDOFF_CONTEXT_INVALID
    failure_ref: missing
'''
        with tempfile.TemporaryDirectory() as directory:
            scenario_path = Path(directory) / "scenario.yaml"
            failure_path = Path(directory) / "failures.yaml"
            scenario_path.write_text(scenario_content, encoding="utf-8")
            failure_path.write_text(
                '''schema_version: "1.0"
scenario_id: support-handoff
failures:
  known:
    retry_count: 3
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported failure operator"):
                load_failure_fixtures(failure_path)
            failure_path.write_text(
                '''schema_version: "1.0"
scenario_id: support-handoff
failures:
  known:
    omit_receiver_input_fields: [request_text]
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unknown failure_ref"):
                load_scenario(scenario_path, failure_path)

    def test_rejects_unknown_receiver_mapping(self) -> None:
        content = '''schema_version: "1.0"
scenario_id: support-handoff
confidence_threshold: 0.80
route_receivers: {billing: unknown-specialist, technical: technical-specialist, general: general-specialist}
cases: []
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "route_receivers.billing"):
                load_scenario(path)

    def test_rejects_duplicate_case_ids(self) -> None:
        case_body = '''    ticket_id: TCK-1001
    request: duplicate
    router_mode: code
    expected_status: SUCCEEDED
    expected_proposed_route: billing
    expected_confidence: 1.0
    expected_selected_route: billing
    expected_receiver: billing-specialist
    expected_policy_outcome: selected
    expected_fallback_applied: false
    expected_specialist_invoked: true
'''
        content = (
            'schema_version: "1.0"\nscenario_id: support-handoff\nconfidence_threshold: 0.80\n'
            'route_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}\n'
            'cases:\n  - id: duplicate\n'
            + case_body
            + '  - id: duplicate\n'
            + case_body
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "case ids must be unique"):
                load_scenario(path)

    async def test_scripted_route_is_consumed_at_most_once(self) -> None:
        provider = ScriptedRouteProvider.from_file()
        self.assertEqual(
            await provider.next_decision(case_id="model-technical-handoff", request="x"),
            {"route": "technical", "confidence": 0.92},
        )
        with self.assertRaises(ScriptedRouteError):
            await provider.next_decision(case_id="model-technical-handoff", request="x")
        with self.assertRaises(ScriptedRouteError):
            await provider.next_decision(case_id="missing", request="x")


if __name__ == "__main__":
    unittest.main()
