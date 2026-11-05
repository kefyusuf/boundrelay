"""Failure-taxonomy preservation inside the corrected graph nodes."""
import json
import tempfile
import unittest
from pathlib import Path

from boundrelay_m3_langgraph import graph


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def run_case(self, key):
        return graph.run_corrected(key, self.trace)

    def test_declared_failure_becomes_failed_outcome(self):
        result = self.run_case("parallel-partial-failure")
        self.assertEqual(result["status"], "PARTIAL")
        delivery = result["worker_outcomes"][2]
        self.assertEqual(delivery["worker_id"], "delivery-status")
        self.assertEqual(delivery["status"], "FAILED")
        self.assertIsNone(delivery["output"])
        self.assertEqual(delivery["failure_code"], "WORKER_EXECUTION_FAILED")
        self.assertEqual(result["brief"]["missing_workers"], ["delivery-status"])
        self.assertEqual(result["failure_code"], None)
        self.assertTrue(result["synthesis_invoked"])

    def test_invalid_output_never_becomes_a_fact(self):
        result = self.run_case("parallel-invalid-output")
        self.assertEqual(result["status"], "PARTIAL")
        payment = result["worker_outcomes"][1]
        self.assertEqual(payment["worker_id"], "payment-status")
        self.assertEqual(payment["status"], "FAILED")
        self.assertIsNone(payment["output"])
        self.assertEqual(payment["failure_code"], "INVALID_WORKER_OUTPUT")
        self.assertNotIn("UNKNOWN", json.dumps(result))
        self.assertEqual(result["brief"]["missing_workers"], ["payment-status"])

    def test_all_failed_blocks_synthesis(self):
        result = self.run_case("parallel-all-failed")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"], "ALL_WORKERS_FAILED")
        self.assertIsNone(result["brief"])
        self.assertFalse(result["synthesis_invoked"])
        self.assertEqual(
            [outcome["failure_code"] for outcome in result["worker_outcomes"]],
            ["WORKER_EXECUTION_FAILED"] * 3)
        self.assertNotIn("synthesize",
                         [step["step_name"] for step in result["attribution"]["steps"]])
        self.assertEqual(result["attribution"]["totals"]["attempts"], 3)


if __name__ == "__main__":
    unittest.main()
