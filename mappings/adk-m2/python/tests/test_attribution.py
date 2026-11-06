"""Attribution: the M6/M2 rules mirrored (step kind by mode, totals = sum)."""
import unittest

from boundrelay_m2_adk import attribution
from boundrelay_m2_adk import fixtures

TABLES = {
    "latency_ms": {
        "classify": 30,
        "receiver.billing-specialist": 10,
        "receiver.technical-specialist": 11,
        "receiver.general-specialist": 12,
    },
    "price_table": {"route": 0, "model_decision": 2, "handoff": 0},
}


class StepKindTests(unittest.TestCase):
    def test_classify_kind_depends_on_the_router_mode(self):
        self.assertEqual(attribution.step_kind("classify", "model"),
                         "model_decision")
        self.assertEqual(attribution.step_kind("classify", "code"), "route")

    def test_receiver_steps_are_handoffs(self):
        for receiver in fixtures.RECEIVER_NAMES:
            self.assertEqual(attribution.step_kind(f"receiver.{receiver}",
                                                   "model"), "handoff")

    def test_unknown_step_raises(self):
        with self.assertRaises(ValueError):
            attribution.step_kind("tool.lookup_order", "model")


class BuildAttributionTests(unittest.TestCase):
    def test_model_mode_success_record(self):
        record = attribution.build_attribution(
            [("classify", 1), ("receiver.technical-specialist", 1)],
            TABLES, "model")
        self.assertEqual(record["steps"], [
            {"step_name": "classify", "latency_ms": 30, "cost_cents": 2,
             "attempts": 1},
            {"step_name": "receiver.technical-specialist", "latency_ms": 11,
             "cost_cents": 0, "attempts": 1},
        ])
        self.assertEqual(record["totals"],
                         {"latency_ms": 41, "cost_cents": 2, "attempts": 2})

    def test_code_mode_classify_is_priced_as_route(self):
        record = attribution.build_attribution([("classify", 1)],
                                               TABLES, "code")
        self.assertEqual(record["steps"][0]["cost_cents"], 0)

    def test_totals_equal_the_sum_of_steps(self):
        record = attribution.build_attribution(
            [("classify", 1), ("receiver.billing-specialist", 1)],
            TABLES, "code")
        for key in ("latency_ms", "cost_cents", "attempts"):
            self.assertEqual(record["totals"][key],
                             sum(step[key] for step in record["steps"]))

    def test_empty_records_raise(self):
        with self.assertRaises(ValueError):
            attribution.build_attribution([], TABLES, "model")

    def test_unknown_step_or_kind_raises(self):
        with self.assertRaises(ValueError):
            attribution.build_attribution([("mystery", 1)], TABLES, "model")


if __name__ == "__main__":
    unittest.main()
