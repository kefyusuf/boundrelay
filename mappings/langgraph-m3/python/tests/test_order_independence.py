"""Completion-order independence of the brief (feasible permutations)."""
import itertools
import tempfile
import unittest
from pathlib import Path

from boundrelay_m3_langgraph import fixtures, graph, results


class OrderIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def test_brief_equal_across_feasible_completion_orders(self):
        complete = graph.run_corrected("parallel-complete", self.trace)
        out_of_order = graph.run_corrected("parallel-out-of-order", self.trace)
        # Same worker fixture, opposite feasible completion orders.
        self.assertEqual(complete["brief"], out_of_order["brief"])
        self.assertEqual(complete["worker_outcomes"],
                         out_of_order["worker_outcomes"])
        self.assertEqual(complete["status"], out_of_order["status"])

    def test_canonical_order_invariant_under_all_permutations(self):
        golden = fixtures.load_golden("parallel-complete")
        outcomes = golden["worker_outcomes"]
        canonical = tuple(outcomes)
        for permutation in itertools.permutations(outcomes):
            with self.subTest(order=[o["worker_id"] for o in permutation]):
                self.assertEqual(
                    results.canonicalize_outcomes(permutation, "ORD-1001"),
                    canonical)


if __name__ == "__main__":
    unittest.main()
