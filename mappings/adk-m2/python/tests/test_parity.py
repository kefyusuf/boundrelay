"""Five-case parity: the ADK run vs the M2 golden result projections.

Parity boundary (mirrors the P5a/M8 mapping design): the mapping result
minus run_id/trace_path must deep-equal the golden result_projection
(attribution included, deep-equal), every result must satisfy the
closed M2 handoff-result schema, and the trace must be ADK's native
event stream.
"""
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from boundrelay_m2_adk import fixtures, mapping, results

ROOT = fixtures.ROOT
SCHEMA = Draft202012Validator(json.loads(
    (ROOT / "contracts/results/handoff-result.schema.json")
    .read_text(encoding="utf-8")))
NON_PARITY_FIELDS = ("run_id", "trace_path")


class FiveCaseParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = Path(self.tmp.name) / "trace.jsonl"

    def test_result_projection_equals_golden_for_all_five_cases(self):
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


class NativeTraceTests(unittest.TestCase):
    """The trace is ADK's own event stream, one JSON event per line."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = Path(self.tmp.name) / "trace.jsonl"

    def _records(self, case_id, **overrides):
        mapping.run_case(case_id, str(self.trace), **overrides)
        lines = self.trace.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines, "the native trace must not be empty")
        return [json.loads(line) for line in lines]

    def test_model_case_writes_the_function_call_and_response_events(self):
        records = self._records("model-technical-handoff")
        calls = [record["content"]["parts"][0]["function_call"]
                 for record in records
                 if record.get("content") and record["content"]["parts"]
                 and "function_call" in record["content"]["parts"][0]]
        self.assertEqual([call["name"] for call in calls],
                         ["handoff_to_specialist"])
        self.assertEqual(calls[0]["args"],
                         {"route": "technical", "confidence": 0.92})
        responses = [record["content"]["parts"][0]["function_response"]
                     for record in records
                     if record.get("content") and record["content"]["parts"]
                     and "function_response" in record["content"]["parts"][0]]
        self.assertEqual([response["name"] for response in responses],
                         ["handoff_to_specialist"])
        for record in records:
            self.assertEqual(record["author"], "support_router")

    def test_code_case_writes_the_code_router_events(self):
        records = self._records("code-billing-handoff")
        self.assertTrue(records)
        for record in records:
            self.assertEqual(record["author"], "code_router")

    def test_model_failure_case_writes_a_framework_error_event(self):
        records = self._records("handoff-context-loss")
        errors = [record for record in records if record.get("error_code")]
        self.assertTrue(errors, "the framework error event must be traced")
        self.assertEqual(errors[0]["error_code"],
                         "HandoffContextInvalidFailure")
        self.assertIn("request_text", errors[0]["error_message"])

    def test_code_failure_case_writes_a_terminal_framework_record(self):
        records = self._records("handoff-receiver-unavailable")
        self.assertTrue(records)
        self.assertEqual(records[0]["author"], "code_router")


if __name__ == "__main__":
    unittest.main()
