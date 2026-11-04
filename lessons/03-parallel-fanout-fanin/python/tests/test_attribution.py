import json
import unittest
from pathlib import Path
import tempfile

from boundrelay_m3.runner import run_case

ROOT = Path(__file__).resolve().parents[4]
RESULT_SCHEMA = json.loads((ROOT / "contracts/results/order-brief-result.schema.json").read_text(encoding="utf-8"))


class AttributionProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_attribution_present_and_sums_match(self):
        with tempfile.TemporaryDirectory() as directory:
            complete = await run_case(
                case_id="parallel-complete", trace_path=str(Path(directory) / "c.jsonl"))
            failed = await run_case(
                case_id="parallel-all-failed", trace_path=str(Path(directory) / "f.jsonl"))
        self.assertEqual(complete["attribution"], {
            "steps": [
                {"step_name": "worker.order-details", "latency_ms": 10, "cost_cents": 0, "attempts": 1},
                {"step_name": "worker.payment-status", "latency_ms": 11, "cost_cents": 0, "attempts": 1},
                {"step_name": "worker.delivery-status", "latency_ms": 12, "cost_cents": 0, "attempts": 1},
                {"step_name": "synthesize", "latency_ms": 15, "cost_cents": 0, "attempts": 1}],
            "totals": {"latency_ms": 48, "cost_cents": 0, "attempts": 4}})
        self.assertEqual(failed["attribution"], {
            "steps": [
                {"step_name": "worker.order-details", "latency_ms": 10, "cost_cents": 0, "attempts": 1},
                {"step_name": "worker.payment-status", "latency_ms": 11, "cost_cents": 0, "attempts": 1},
                {"step_name": "worker.delivery-status", "latency_ms": 12, "cost_cents": 0, "attempts": 1}],
            "totals": {"latency_ms": 33, "cost_cents": 0, "attempts": 3}})

    async def test_attribution_absent_rejected_by_schema(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(RESULT_SCHEMA)
        with tempfile.TemporaryDirectory() as directory:
            result = await run_case(
                case_id="parallel-complete", trace_path=str(Path(directory) / "t.jsonl"))
        stripped = {key: value for key, value in result.items() if key != "attribution"}
        self.assertTrue(validator.is_valid(result))
        self.assertFalse(validator.is_valid(stripped))
