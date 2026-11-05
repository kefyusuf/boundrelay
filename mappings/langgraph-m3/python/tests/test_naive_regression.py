"""The naive regression: uncapped dispatch + default propagation.

The naive graph trusts LangGraph's defaults: all three branches dispatch
uncapped, worker outputs are published unvalidated (invalid output
becomes a fact), and a declared worker error propagates by default -
crashing the whole graph run. It is retained honestly as the teaching
artifact; its divergence is asserted, not normalized.
"""
import json
import tempfile
import unittest
from pathlib import Path

from boundrelay_m3_langgraph import graph, naive, results


class NaiveDefaultPropagationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "naive-trace.jsonl")

    def test_declared_error_crashes_the_graph_run(self):
        for key in ("parallel-partial-failure", "parallel-all-failed"):
            with self.subTest(case=key):
                with self.assertRaises(graph.WorkerExecutionError) as caught:
                    naive.run_naive(key, self.trace)
                self.assertIn("Declared worker failure", str(caught.exception))

    def test_uncapped_dispatch_is_observed_not_normalized(self):
        result = naive.run_naive("parallel-complete", self.trace)
        self.assertEqual(result["peak_concurrency"], 3,
                         "the framework dispatched all three uncapped")
        self.assertIsNone(result["concurrency_limit"], "no cap was applied")
        # The corrected graph, same case: capped at 2.
        corrected = graph.run_corrected("parallel-complete", self.trace)
        self.assertEqual(corrected["peak_concurrency"], 2)

    def test_invalid_output_becomes_a_fact_in_naive_mode(self):
        result = naive.run_naive("parallel-invalid-output", self.trace)
        self.assertIn("UNKNOWN", json.dumps(result))
        self.assertFalse(results.validate_result(result),
                         "the naive result violates the closed schema")
        payment = next(outcome for outcome in result["worker_outcomes"]
                       if outcome["worker_id"] == "payment-status")
        self.assertEqual(payment["output"]["payment_status"], "UNKNOWN")
        self.assertEqual(payment["failure_code"], None,
                         "no failure taxonomy exists in naive mode")

    def test_naive_success_still_fails_the_closed_schema(self):
        result = naive.run_naive("parallel-complete", self.trace)
        self.assertFalse(results.validate_result(result),
                         "uncapped peak/no-limit already break the schema")

    def test_naive_sections_are_arrival_ordered_not_canonical(self):
        result = naive.run_naive("parallel-complete", self.trace)
        sections = result["brief"]["sections"]
        outcomes = result["worker_outcomes"]
        canonical = [o["worker_id"]
                     for o in results.canonicalize_outcomes(outcomes,
                                                            "ORD-1001")]
        self.assertEqual([s["worker_id"] for s in sections],
                         [o["worker_id"] for o in outcomes],
                         "sections are appended in arrival order")
        self.assertEqual(canonical,
                         ["order-details", "payment-status",
                          "delivery-status"],
                         "canonical order exists independently of arrival")


if __name__ == "__main__":
    unittest.main()
