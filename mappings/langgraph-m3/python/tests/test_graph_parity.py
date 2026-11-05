"""Six-case business-projection parity: corrected graph vs M3 goldens.

Parity boundary (accepted design section 4): the mapping result minus
run_id/trace_path must deep-equal the golden result_projection
(attribution included, deep-equal), and every result must satisfy the
closed M3 result schema. Traces are LangGraph's native stream and are
explicitly not compared.
"""
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from boundrelay_m3_langgraph import fixtures, graph, results

ROOT = fixtures.ROOT
SCHEMA = Draft202012Validator(json.loads(
    (ROOT / "contracts/results/order-brief-result.schema.json")
    .read_text(encoding="utf-8")))
NON_PARITY_FIELDS = ("run_id", "trace_path")


class SixCaseParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = Path(self.tmp.name) / "trace.jsonl"

    def test_business_projection_equals_golden_for_all_six_cases(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                result = graph.run_corrected(key, str(self.trace))
                projection = fixtures.load_golden(key)  # result_projection
                actual = {field: value for field, value in result.items()
                          if field not in NON_PARITY_FIELDS}
                self.assertEqual(actual, projection)
                self.assertEqual(result["attribution"],
                                 projection["attribution"])

    def test_results_satisfy_the_closed_schema(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                result = graph.run_corrected(key, str(self.trace))
                self.assertTrue(results.validate_result(result))
                SCHEMA.validate(result)

    def test_native_stream_trace_is_written(self):
        result = graph.run_corrected("parallel-complete", str(self.trace))
        lines = self.trace.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines, "the native stream trace must not be empty")
        chunks = [json.loads(line) for line in lines]
        names = {name for chunk in chunks for name in chunk}
        for worker_id in fixtures.WORKER_IDS:
            self.assertIn(f"worker.{worker_id}", names)
        self.assertIn("collect", names)
        self.assertIn("finalize", names)
        result_chunks = [chunk for chunk in chunks
                         if isinstance(chunk.get("finalize"), dict)
                         and "result" in chunk["finalize"]]
        self.assertEqual(len(result_chunks), 1,
                         "exactly one finalize chunk publishes the result")
        self.assertEqual(result["trace_path"], str(self.trace))


if __name__ == "__main__":
    unittest.main()
