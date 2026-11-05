"""Structural result validation mirroring the closed M3 result schema."""
import unittest

from boundrelay_m3_langgraph import fixtures, results


def golden_with_plumbing(case_key):
    projection = fixtures.load_golden(case_key)
    result = dict(projection)
    result["run_id"] = "run-m8-test"
    result["trace_path"] = ".boundrelay/mapping-test/trace.jsonl"
    return result


class ValidateResultTests(unittest.TestCase):
    def test_golden_projections_validate(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                self.assertTrue(results.validate_result(
                    golden_with_plumbing(key)))

    def test_rejects_extra_or_missing_fields(self):
        result = golden_with_plumbing("parallel-complete")
        drifted = {**result, "surprise": 1}
        self.assertFalse(results.validate_result(drifted))
        incomplete = {key: value for key, value in result.items()
                      if key != "failure_code"}
        self.assertFalse(results.validate_result(incomplete))

    def test_rejects_status_conditionals_drift(self):
        result = golden_with_plumbing("parallel-complete")
        broken = {**result, "status": "FAILED"}
        self.assertFalse(results.validate_result(broken))
        partial = golden_with_plumbing("parallel-partial-failure")
        self.assertFalse(results.validate_result(
            {**partial, "failure_code": "ALL_WORKERS_FAILED"}))
        failed = golden_with_plumbing("parallel-all-failed")
        self.assertFalse(results.validate_result(
            {**failed, "brief": {"order_id": "ORD-1001", "sections": [],
                                 "missing_workers": [], "complete": True}}))

    def test_rejects_enum_and_pattern_drift(self):
        result = golden_with_plumbing("parallel-complete")
        self.assertFalse(results.validate_result({**result, "order_id": "1001"}))
        outcomes = [dict(outcome) for outcome in result["worker_outcomes"]]
        outcomes[0] = {**outcomes[0], "worker_id": "mystery-worker"}
        self.assertFalse(results.validate_result(
            {**result, "worker_outcomes": outcomes}))
        self.assertFalse(results.validate_result(
            {**result, "peak_concurrency": 3}))


class CollectorAndSynthesizerTests(unittest.TestCase):
    def test_canonicalize_restores_canonical_order(self):
        golden = fixtures.load_golden("parallel-complete")
        outcomes = golden["worker_outcomes"]
        permuted = [outcomes[2], outcomes[0], outcomes[1]]
        canonical = results.canonicalize_outcomes(permuted, "ORD-1001")
        self.assertEqual(canonical, tuple(outcomes))

    def test_canonicalize_rejects_bad_fan_in(self):
        golden = fixtures.load_golden("parallel-complete")
        outcomes = golden["worker_outcomes"]
        with self.assertRaises(ValueError):
            results.canonicalize_outcomes(outcomes[:2], "ORD-1001")
        duplicated = [outcomes[0], outcomes[0], outcomes[1]]
        with self.assertRaises(ValueError):
            results.canonicalize_outcomes(duplicated, "ORD-1001")
        with self.assertRaises(ValueError):
            results.canonicalize_outcomes(outcomes, "ORD-9999")

    def test_synthesize_brief_matches_golden(self):
        for key in ("parallel-complete", "parallel-partial-failure",
                    "parallel-invalid-output"):
            golden = fixtures.load_golden(key)
            outcomes = golden["worker_outcomes"]
            brief = results.synthesize_brief("ORD-1001", outcomes)
            self.assertEqual(brief, golden["brief"], key)

    def test_synthesize_rejects_empty_evidence(self):
        with self.assertRaises(ValueError):
            results.synthesize_brief("ORD-1001", [])

    def test_validate_worker_output_rejects_invalid_shapes(self):
        self.assertTrue(results.validate_worker_output(
            "payment-status", {"order_id": "ORD-1001", "payment_status": "PAID"},
            "ORD-1001").valid)
        self.assertFalse(results.validate_worker_output(
            "payment-status", {"order_id": "ORD-1001", "payment_status": "UNKNOWN"},
            "ORD-1001").valid)
        self.assertFalse(results.validate_worker_output(
            "payment-status", {"order_id": "ORD-9999", "payment_status": "PAID"},
            "ORD-1001").valid)


if __name__ == "__main__":
    unittest.main()
