"""Attribution rules mirroring M6: latency = table x attempts; totals = sum."""
import unittest

from boundrelay_m3_langgraph import attribution, fixtures


TABLES = {
    "latency_ms": {"worker.a": 10, "synthesize": 15},
    "price_table": {"read": 0, "synthesis": 0},
}


class AttributionRuleTests(unittest.TestCase):
    def test_latency_multiplies_attempts_and_totals_sum(self):
        built = attribution.build_attribution(
            [("worker.a", 2), ("synthesize", 1)], TABLES)
        self.assertEqual(built["steps"], [
            {"step_name": "worker.a", "latency_ms": 20, "cost_cents": 0,
             "attempts": 2},
            {"step_name": "synthesize", "latency_ms": 15, "cost_cents": 0,
             "attempts": 1},
        ])
        self.assertEqual(built["totals"], {"latency_ms": 35, "cost_cents": 0,
                                           "attempts": 3})

    def test_unknown_step_and_bad_attempts_raise(self):
        with self.assertRaises(ValueError):
            attribution.build_attribution([("worker.mystery", 1)], TABLES)
        with self.assertRaises(ValueError):
            attribution.build_attribution([("worker.a", 0)], TABLES)
        with self.assertRaises(ValueError):
            attribution.build_attribution([], TABLES)

    def test_step_kinds(self):
        self.assertEqual(attribution.step_kind("synthesize"), "synthesis")
        self.assertEqual(attribution.step_kind("worker.order-details"), "read")
        with self.assertRaises(ValueError):
            attribution.step_kind("mystery")
    def test_golden_totals_reproduced_from_fixture_tables(self):
        tables = fixtures.load_attribution_projection()
        worker_records = [(f"worker.{worker_id}", 1)
                          for worker_id in fixtures.WORKER_IDS]
        with_synthesis = attribution.build_attribution(
            worker_records + [("synthesize", 1)], tables)
        golden = fixtures.load_golden("parallel-complete")
        self.assertEqual(with_synthesis, golden["attribution"])
        self.assertEqual(with_synthesis["totals"]["latency_ms"], 48)
        without_synthesis = attribution.build_attribution(worker_records, tables)
        self.assertEqual(without_synthesis,
                         fixtures.load_golden("parallel-all-failed")["attribution"])
        self.assertEqual(without_synthesis["totals"]["attempts"], 3)


if __name__ == "__main__":
    unittest.main()
