"""Result assembly: structural mirror of the closed handoff-result schema."""
import unittest

from boundrelay_m2_adk import results

ATTRIBUTION = {
    "steps": [
        {"step_name": "classify", "latency_ms": 30, "cost_cents": 2,
         "attempts": 1},
        {"step_name": "receiver.billing-specialist", "latency_ms": 10,
         "cost_cents": 0, "attempts": 1},
    ],
    "totals": {"latency_ms": 40, "cost_cents": 2, "attempts": 2},
}


def success_result(**overrides):
    fields = {
        "run_id": "run-1", "case_id": "code-billing-handoff",
        "router_mode": "code", "status": "SUCCEEDED",
        "proposed_route": "billing", "selected_route": "billing",
        "receiver": "billing-specialist", "fallback_applied": False,
        "specialist_invoked": True, "failure_code": None,
        "trace_path": "trace.jsonl", "attribution": ATTRIBUTION,
    }
    fields.update(overrides)
    return results.assemble_result(**fields)


class ValidateResultTests(unittest.TestCase):
    def test_valid_success_result_passes(self):
        self.assertTrue(results.validate_result(success_result()))

    def test_valid_handoff_failure_result_passes(self):
        result = success_result(
            case_id="handoff-context-loss", router_mode="model",
            status="FAILED", specialist_invoked=False,
            failure_code="HANDOFF_CONTEXT_INVALID",
            attribution={"steps": [ATTRIBUTION["steps"][0]],
                         "totals": {"latency_ms": 30, "cost_cents": 2,
                                    "attempts": 1}})
        self.assertTrue(results.validate_result(result))

    def test_valid_invalid_route_result_requires_null_selection(self):
        result = success_result(
            case_id="model-technical-handoff", router_mode="model",
            status="FAILED", proposed_route=None, selected_route=None,
            receiver=None, specialist_invoked=False,
            failure_code="INVALID_ROUTE_DECISION",
            attribution={"steps": [ATTRIBUTION["steps"][0]],
                         "totals": {"latency_ms": 30, "cost_cents": 2,
                                    "attempts": 1}})
        self.assertTrue(results.validate_result(result))
        broken = dict(result, proposed_route="billing")
        self.assertFalse(results.validate_result(broken))

    def test_success_requires_specialist_invoked_and_no_failure(self):
        broken = dict(success_result(), specialist_invoked=False)
        self.assertFalse(results.validate_result(broken))
        broken = dict(success_result(),
                      failure_code="HANDOFF_RECEIVER_UNAVAILABLE")
        self.assertFalse(results.validate_result(broken))

    def test_failure_requires_a_taxonomy_code(self):
        broken = dict(success_result(), status="FAILED",
                      specialist_invoked=False, failure_code=None)
        self.assertFalse(results.validate_result(broken))
        broken = dict(success_result(), status="FAILED",
                      specialist_invoked=False, failure_code="NOT_A_CODE")
        self.assertFalse(results.validate_result(broken))

    def test_handoff_failures_require_a_full_selection(self):
        broken = dict(success_result(), status="FAILED",
                      specialist_invoked=False, receiver=None,
                      failure_code="HANDOFF_CONTEXT_INVALID")
        self.assertFalse(results.validate_result(broken))

    def test_exact_field_set_is_enforced(self):
        result = success_result()
        broken = dict(result)
        broken.pop("fallback_applied")
        self.assertFalse(results.validate_result(broken))
        broken = dict(result, extra=1)
        self.assertFalse(results.validate_result(broken))

    def test_totals_must_equal_the_sum_of_steps(self):
        attribution = {"steps": ATTRIBUTION["steps"],
                       "totals": {"latency_ms": 39, "cost_cents": 2,
                                  "attempts": 2}}
        broken = dict(success_result(), attribution=attribution)
        self.assertFalse(results.validate_result(broken))

    def test_non_finite_json_fails(self):
        broken = dict(success_result(), run_id=float("nan"))
        self.assertFalse(results.validate_result(broken))

    def test_scenario_id_is_pinned(self):
        broken = dict(success_result(), scenario_id="order-investigation")
        self.assertFalse(results.validate_result(broken))


class AssembleResultTests(unittest.TestCase):
    def test_assemble_validates_before_publication(self):
        with self.assertRaises(ValueError):
            success_result(status="SUCCEEDED", receiver=None)

    def test_assemble_returns_an_independent_copy(self):
        result = success_result()
        result["attribution"]["steps"][0]["attempts"] = 99
        fresh = success_result()
        self.assertEqual(fresh["attribution"]["steps"][0]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
