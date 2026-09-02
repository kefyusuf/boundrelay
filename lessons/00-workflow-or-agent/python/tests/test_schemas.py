import unittest

from boundrelay_m0.schemas import validate_route_decision, validate_run_event, validate_run_result


class SchemaAdapterTests(unittest.TestCase):
    def test_accepts_valid_shared_contract_values(self) -> None:
        self.assertTrue(validate_route_decision({"route": "billing", "confidence": 0.9}).ok)
        self.assertTrue(validate_run_event({
            "schema_version": "1.0",
            "event_id": "evt-1",
            "run_id": "run-1",
            "sequence": 1,
            "type": "run.created",
            "timestamp": "2026-09-02T00:00:00Z",
            "source": "python",
            "data": {},
        }).ok)
        self.assertTrue(validate_run_result({
            "schema_version": "1.0",
            "run_id": "run-1",
            "scenario_id": "support-triage",
            "case_id": "billing-duplicate-charge",
            "mode": "deterministic",
            "status": "SUCCEEDED",
            "selected_route": "billing",
            "specialist_invoked": True,
            "failure_code": None,
            "trace_path": ".boundrelay/m0/trace.jsonl",
        }).ok)

    def test_rejects_non_finite_confidence(self) -> None:
        for confidence in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(confidence=confidence):
                result = validate_route_decision({"route": "billing", "confidence": confidence})
                self.assertFalse(result.ok)
                self.assertIn("finite", " ".join(result.errors))

    def test_rejects_oversized_integer_confidence_without_raising(self) -> None:
        result = validate_route_decision({"route": "billing", "confidence": 10**10000})

        self.assertFalse(result.ok)
        self.assertIn("confidence", " ".join(result.errors))

    def test_rejects_invalid_route_and_inconsistent_result_values(self) -> None:
        self.assertFalse(validate_route_decision({"route": "unknown", "confidence": 0.9}).ok)
        self.assertFalse(validate_run_result({
            "schema_version": "1.0",
            "run_id": "run-1",
            "scenario_id": "support-triage",
            "case_id": "invalid-model-route",
            "mode": "model",
            "status": "FAILED",
            "selected_route": "billing",
            "specialist_invoked": True,
            "failure_code": None,
            "trace_path": ".boundrelay/m0/trace.jsonl",
        }).ok)


if __name__ == "__main__":
    unittest.main()
