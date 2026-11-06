"""Result assembly: closed M1 result shape, validated before publication."""
import unittest

from boundrelay_m1_openai import results


def valid_result(**overrides):
    result = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "scenario_id": "order-investigation",
        "case_id": "agent-delayed-shipment",
        "mode": "agent",
        "status": "SUCCEEDED",
        "answer": "Order ORD-1001 is delayed.",
        "failure_code": None,
        "model_steps": 3,
        "tokens_used": 129,
        "tool_invocations": 2,
        "trace_path": "trace.jsonl",
        "attribution": {
            "steps": [{"step_name": "model", "latency_ms": 90,
                       "cost_cents": 6, "attempts": 3}],
            "totals": {"latency_ms": 90, "cost_cents": 6, "attempts": 3},
        },
    }
    result.update(overrides)
    return result


class ValidateResultTests(unittest.TestCase):
    def test_accepts_a_valid_success_result(self):
        self.assertTrue(results.validate_result(valid_result()))

    def test_accepts_a_valid_failure_result(self):
        result = valid_result(status="FAILED", answer=None,
                              failure_code="STEP_BUDGET_EXCEEDED")
        self.assertTrue(results.validate_result(result))

    def test_rejects_extra_or_missing_fields(self):
        self.assertFalse(results.validate_result(valid_result(extra=1)))
        broken = valid_result()
        del broken["answer"]
        self.assertFalse(results.validate_result(broken))

    def test_rejects_success_with_failure_code(self):
        self.assertFalse(results.validate_result(
            valid_result(failure_code="UNKNOWN_TOOL")))

    def test_rejects_failure_with_answer(self):
        self.assertFalse(results.validate_result(
            valid_result(status="FAILED", answer="text",
                         failure_code="UNKNOWN_TOOL")))

    def test_rejects_unknown_failure_code(self):
        self.assertFalse(results.validate_result(
            valid_result(status="FAILED", answer=None,
                         failure_code="NOT_A_CODE")))

    def test_rejects_totals_not_equal_to_steps(self):
        attribution = {"steps": [{"step_name": "model", "latency_ms": 90,
                                  "cost_cents": 6, "attempts": 3}],
                       "totals": {"latency_ms": 30, "cost_cents": 2,
                                  "attempts": 1}}
        self.assertFalse(results.validate_result(
            valid_result(attribution=attribution)))

    def test_rejects_non_string_run_id(self):
        self.assertFalse(results.validate_result(valid_result(run_id=7)))


class AssembleResultTests(unittest.TestCase):
    def test_assembles_and_deep_copies_attribution(self):
        attribution = {"steps": [{"step_name": "model", "latency_ms": 30,
                                  "cost_cents": 2, "attempts": 1}],
                       "totals": {"latency_ms": 30, "cost_cents": 2,
                                  "attempts": 1}}
        result = results.assemble_result(
            run_id="run-1", trace_path="t.jsonl",
            case_id="agent-unknown-tool", mode="agent", status="FAILED",
            answer=None, failure_code="UNKNOWN_TOOL", model_steps=1,
            tokens_used=25, tool_invocations=0, attribution=attribution)
        self.assertEqual(result["failure_code"], "UNKNOWN_TOOL")
        attribution["steps"][0]["attempts"] = 99
        self.assertEqual(result["attribution"]["steps"][0]["attempts"], 1)

    def test_rejects_invalid_assembly(self):
        with self.assertRaises(ValueError):
            results.assemble_result(
                run_id="run-1", trace_path="t.jsonl", case_id="c",
                mode="agent", status="MAYBE", answer=None,
                failure_code=None, model_steps=0, tokens_used=0,
                tool_invocations=0, attribution={"steps": [], "totals": {}})


if __name__ == "__main__":
    unittest.main()
