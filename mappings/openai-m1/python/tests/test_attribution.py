"""Attribution rules (M6): fixture tables x attempts, totals = sum."""
import unittest

from boundrelay_m1_openai import attribution, fixtures


TABLES = {"latency_ms": {"model": 30, "tool.lookup_order": 8,
                         "tool.lookup_shipment": 9},
          "price_table": {"model_decision": 2, "tool_call": 1}}


class AttributionTests(unittest.TestCase):
    def test_model_step_pricing(self):
        built = attribution.build_attribution([("model", 3)], TABLES)
        self.assertEqual(built["steps"], [{"step_name": "model",
                                           "latency_ms": 90, "cost_cents": 6,
                                           "attempts": 3}])
        self.assertEqual(built["totals"], {"latency_ms": 90, "cost_cents": 6,
                                           "attempts": 3})

    def test_tool_steps_priced_per_call(self):
        built = attribution.build_attribution(
            [("model", 1), ("tool.lookup_order", 1)], TABLES)
        self.assertEqual(built["totals"],
                         {"latency_ms": 38, "cost_cents": 3, "attempts": 2})

    def test_totals_equal_sum_of_steps(self):
        records = [("model", 2), ("tool.lookup_order", 1),
                   ("tool.lookup_shipment", 1)]
        built = attribution.build_attribution(records, TABLES)
        for key in ("latency_ms", "cost_cents", "attempts"):
            self.assertEqual(built["totals"][key],
                             sum(step[key] for step in built["steps"]))

    def test_unknown_step_rejected(self):
        with self.assertRaises(ValueError):
            attribution.build_attribution([("synthesize", 1)], TABLES)

    def test_invalid_attempts_rejected(self):
        with self.assertRaises(ValueError):
            attribution.build_attribution([("model", 0)], TABLES)

    def test_scenario_fixture_tables_build_the_golden_totals(self):
        case = fixtures.load_case("agent-delayed-shipment")
        built = attribution.build_attribution(
            [("model", 3), ("tool.lookup_order", 1),
             ("tool.lookup_shipment", 1)],
            {"latency_ms": case.latency_ms, "price_table": case.price_table})
        self.assertEqual(built["totals"],
                         {"latency_ms": 107, "cost_cents": 8, "attempts": 5})


if __name__ == "__main__":
    unittest.main()
