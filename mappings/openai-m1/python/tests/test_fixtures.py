"""Strict fixture loading: checked-in artifacts only, closed validation."""
import unittest

from boundrelay_m1_openai import fixtures


class ScenarioProjectionTests(unittest.TestCase):
    def test_eight_parity_case_keys_enumerated(self):
        scenario = fixtures.load_scenario_projection()
        keys = tuple(case["id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 8, "the canonical M1 set is eight cases")
        self.assertEqual(keys, fixtures.PARITY_CASE_KEYS)

    def test_attribution_tables_present(self):
        scenario = fixtures.load_scenario_projection()
        self.assertEqual(scenario["attribution"]["latency_ms"]["model"], 30)
        self.assertEqual(scenario["attribution"]["price_table"]["model_decision"], 2)
        self.assertEqual(scenario["attribution"]["price_table"]["tool_call"], 1)

    def test_direct_case_defines_a_direct_call(self):
        scenario = fixtures.load_scenario_projection()
        direct = next(case for case in scenario["cases"]
                      if case["id"] == "direct-order-status")
        self.assertEqual(direct["direct_call"]["tool"], "lookup_order")
        self.assertEqual(direct["direct_call"]["arguments"], {"order_id": "ORD-1001"})

    def test_rejects_mutated_scenario(self):
        raw = fixtures._load_json(fixtures.PROJECTION_DIR / "scenario.json")
        raw["extra"] = True
        with self.assertRaises(ValueError):
            fixtures.parse_scenario(raw)

    def test_rejects_wrong_case_count(self):
        raw = fixtures._load_json(fixtures.PROJECTION_DIR / "scenario.json")
        raw["cases"] = raw["cases"][:7]
        with self.assertRaises(ValueError):
            fixtures.parse_scenario(raw)


class FakeModelProjectionTests(unittest.TestCase):
    def test_trajectories_cover_exactly_the_agent_cases(self):
        scenario = fixtures.load_scenario_projection()
        trajectories = fixtures.load_fake_model_projection(scenario)
        agent_cases = {case["id"] for case in scenario["cases"]
                       if case["mode"] == "agent"}
        self.assertEqual(set(trajectories), agent_cases)
        self.assertEqual(len(agent_cases), 7)

    def test_delayed_shipment_trajectory_is_three_turns(self):
        scenario = fixtures.load_scenario_projection()
        turns = fixtures.load_fake_model_projection(scenario)["agent-delayed-shipment"]
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0]["decision"]["tool"], "lookup_order")
        self.assertEqual(turns[2]["decision"]["kind"], "final")

    def test_rejects_unknown_decision_kind(self):
        with self.assertRaises(ValueError):
            fixtures.parse_turn({"schema_version": "1.0",
                                 "decision": {"kind": "route"},
                                 "usage": {"input_tokens": 1, "output_tokens": 1}})


class FakeToolsProjectionTests(unittest.TestCase):
    def test_orders_and_shipments_records(self):
        tools = fixtures.load_fake_tools_projection()
        self.assertEqual(set(tools["orders"]),
                         {"ORD-1001", "ORD-9001", "ORD-9002"})
        self.assertEqual(set(tools["shipments"]), {"SHP-1001"})
        self.assertEqual(tools["orders"]["ORD-9001"], {"behavior": "timeout"})
        self.assertEqual(tools["orders"]["ORD-9002"], {"behavior": "failure"})

    def test_rejects_bad_behavior(self):
        with self.assertRaises(ValueError):
            fixtures.parse_fake_tools({
                "schema_version": "1.0", "scenario_id": "order-investigation",
                "orders": {"ORD-1001": {"behavior": "explode"}},
                "shipments": {},
            })


class GoldenProjectionTests(unittest.TestCase):
    def test_every_parity_case_has_a_golden_projection(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                projection = fixtures.load_golden(key)
                self.assertIn(projection["status"], ("SUCCEEDED", "FAILED"))
                self.assertIn("attribution", projection)

    def test_unknown_golden_case_rejected(self):
        with self.assertRaises(ValueError):
            fixtures.load_golden("not-a-case")


class ArgumentSchemaTests(unittest.TestCase):
    def test_closed_schemas_load_and_enforce_patterns(self):
        for tool, key, prefix in (("lookup_order", "order_id", "ORD-"),
                                  ("lookup_shipment", "shipment_id", "SHP-")):
            schema = fixtures.load_argument_schema(tool)
            self.assertEqual(schema["type"], "object")
            self.assertEqual(schema["required"], [key])
            self.assertTrue(schema["properties"][key]["pattern"]
                            .startswith(f"^{prefix}"))

    def test_unknown_tool_schema_rejected(self):
        with self.assertRaises(ValueError):
            fixtures.load_argument_schema("lookup_customer")


class LoadCaseTests(unittest.TestCase):
    def test_load_case_assembles_one_agent_case(self):
        case = fixtures.load_case("agent-delayed-shipment")
        self.assertEqual(case.mode, "agent")
        self.assertEqual((case.max_steps, case.max_tokens), (3, 129))
        self.assertEqual(len(case.turns), 3)

    def test_load_case_unknown_id_rejected(self):
        with self.assertRaises(ValueError):
            fixtures.load_case("not-a-case")


if __name__ == "__main__":
    unittest.main()
