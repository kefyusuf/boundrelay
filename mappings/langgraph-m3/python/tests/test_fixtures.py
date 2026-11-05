"""Fixture loading validation for the M8 LangGraph mapping.

The mapping reads only checked-in artifacts: the Go fixture projections
(fixtures/goprojections/order-brief/) and the M3 golden projections
(fixtures/goldens/order-brief/). Loading is strict and offline.
"""
import unittest

from boundrelay_m3_langgraph import fixtures


class ScenarioProjectionTests(unittest.TestCase):
    def test_scenario_projection_strict_load(self):
        scenario = fixtures.load_scenario_projection()
        self.assertEqual(scenario["schema_version"], "1.0")
        self.assertEqual(scenario["scenario_id"], "order-brief")
        self.assertEqual(scenario["order_id"], "ORD-1001")
        self.assertEqual(len(scenario["cases"]), 6)
        self.assertEqual(
            tuple(case["case_id"] for case in scenario["cases"]),
            fixtures.PARITY_CASE_KEYS)

    def test_workers_projection_covers_referenced_fixtures(self):
        workers = fixtures.load_workers_projection()
        scenario = fixtures.load_scenario_projection()
        refs = {case["worker_fixture"] for case in scenario["cases"]}
        self.assertEqual(set(workers), refs)
        for instructions in workers.values():
            self.assertEqual(set(instructions), set(fixtures.WORKER_IDS))
        for instruction in (
                item for values in workers.values() for item in values.values()):
            self.assertIn(instruction["operation"], ("return", "raise"))

    def test_attribution_projection_tables(self):
        tables = fixtures.load_attribution_projection()
        self.assertEqual(tables["latency_ms"]["worker.order-details"], 10)
        self.assertEqual(tables["latency_ms"]["synthesize"], 15)
        self.assertEqual(tables["price_table"]["read"], 0)
        self.assertEqual(tables["price_table"]["synthesis"], 0)

    def test_load_case_assembles_run_inputs(self):
        case = fixtures.load_case("parallel-out-of-order")
        self.assertEqual(case.execution_mode, "parallel")
        self.assertEqual(
            case.completion_order,
            ("payment-status", "delivery-status", "order-details"))
        self.assertEqual(case.limit, 2)
        self.assertEqual(
            case.instructions["payment-status"]["output"]["payment_status"],
            "PAID")
        self.assertEqual(
            case.instructions["delivery-status"]["operation"], "return")
        sequential = fixtures.load_case("sequential-complete")
        self.assertEqual(sequential.limit, 1)
        self.assertEqual(sequential.execution_mode, "sequential")

    def test_load_case_rejects_unknown_case(self):
        with self.assertRaises(ValueError):
            fixtures.load_case("no-such-case")

    def test_golden_projection_load(self):
        golden = fixtures.load_golden("parallel-complete")
        self.assertEqual(golden["status"], "SUCCEEDED")
        self.assertEqual(len(golden["worker_outcomes"]), 3)
        self.assertIn("attribution", golden)

    def test_strict_parsing_rejects_tampered_scenario(self):
        raw = fixtures.load_scenario_projection()
        with self.assertRaises(ValueError):
            fixtures.parse_scenario({**raw, "extra": 1})
        with self.assertRaises(ValueError):
            fixtures.parse_scenario({**raw, "schema_version": "9.9"})
        cases = [dict(case) for case in raw["cases"]]
        cases[1]["completion_order"] = ["payment-status", "order-details",
                                        "order-details"]
        with self.assertRaises(ValueError):
            fixtures.parse_scenario({**raw, "cases": cases})


if __name__ == "__main__":
    unittest.main()
