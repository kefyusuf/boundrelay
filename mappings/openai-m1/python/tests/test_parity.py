"""Eight-case parity: the SDK run vs the M1 golden result projections.

Parity boundary (mirrors the M8 mapping design): the mapping result
minus run_id/trace_path must deep-equal the golden result_projection
(attribution included, deep-equal), every result must satisfy the
closed M1 result schema, and the native trace must be the SDK's own
run-item telemetry.
"""
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from boundrelay_m1_openai import fixtures, mapping, results

ROOT = fixtures.ROOT
SCHEMA = Draft202012Validator(json.loads(
    (ROOT / "contracts/results/tool-loop-result.schema.json")
    .read_text(encoding="utf-8")))
NON_PARITY_FIELDS = ("run_id", "trace_path")


class EightCaseParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = Path(self.tmp.name) / "trace.jsonl"

    def test_result_projection_equals_golden_for_all_eight_cases(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                result = mapping.run_case(key, str(self.trace))
                projection = fixtures.load_golden(key)
                actual = {field: value for field, value in result.items()
                          if field not in NON_PARITY_FIELDS}
                self.assertEqual(actual, projection)
                self.assertEqual(result["attribution"],
                                 projection["attribution"])

    def test_results_satisfy_the_closed_schema(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                result = mapping.run_case(key, str(self.trace))
                self.assertTrue(results.validate_result(result))
                SCHEMA.validate(result)

    def test_expected_counters_match_the_scenario_spec(self):
        scenario = fixtures.load_scenario_projection()
        for spec in scenario["cases"]:
            with self.subTest(case=spec["id"]):
                result = mapping.run_case(spec["id"], str(self.trace))
                self.assertEqual(result["model_steps"],
                                 spec["expected_model_steps"])
                self.assertEqual(result["tokens_used"],
                                 spec["expected_tokens_used"])
                self.assertEqual(result["tool_invocations"],
                                 spec["expected_tool_invocations"])


class NativeTraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = Path(self.tmp.name) / "trace.jsonl"

    def test_agent_cases_write_sdk_run_items(self):
        mapping.run_case("agent-delayed-shipment", str(self.trace))
        lines = self.trace.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines, "the native trace must not be empty")
        records = [json.loads(line) for line in lines]
        types = {record["item_type"] for record in records}
        self.assertIn("ToolCallItem", types)
        self.assertIn("ToolCallOutputItem", types)
        self.assertIn("MessageOutputItem", types)
        calls = [record["raw_item"] for record in records
                 if record["item_type"] == "ToolCallItem"]
        self.assertEqual([call["name"] for call in calls],
                         ["lookup_order", "lookup_shipment"])

    def test_failure_cases_write_a_terminal_sdk_record(self):
        mapping.run_case("agent-unknown-tool", str(self.trace))
        lines = self.trace.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        self.assertEqual(records[0]["item_type"], "run.failed")
        self.assertEqual(records[0]["raw_item"]["failure_code"],
                         "UNKNOWN_TOOL")
        self.assertEqual(records[0]["raw_item"]["error_type"],
                         "ModelBehaviorError")

    def test_direct_case_writes_a_direct_invocation_record(self):
        mapping.run_case("direct-order-status", str(self.trace))
        records = [json.loads(line) for line in
                   self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["item_type"], "direct_invocation")
        self.assertEqual(records[0]["raw_item"]["tool"], "lookup_order")
        self.assertEqual(records[0]["raw_item"]["output"]["status"], "SHIPPED")


if __name__ == "__main__":
    unittest.main()
