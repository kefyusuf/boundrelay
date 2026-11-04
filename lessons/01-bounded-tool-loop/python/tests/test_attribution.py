import json
import unittest
from pathlib import Path
import tempfile

from boundrelay_m1.runner import run_scenario_case

ROOT = Path(__file__).resolve().parents[4]
RESULT_SCHEMA = json.loads((ROOT / "contracts/results/tool-loop-result.schema.json").read_text(encoding="utf-8"))


def fixed_ids(prefix):
    sequence = 0

    def next_id():
        nonlocal sequence
        sequence += 1
        return f"{prefix}-{sequence}"

    return next_id


def fixed_clock():
    from datetime import datetime, timezone
    return datetime(2026, 9, 2, tzinfo=timezone.utc)


class AttributionProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_attribution_present_and_sums_match(self):
        with tempfile.TemporaryDirectory() as directory:
            direct = await run_scenario_case(
                mode="direct", case_id="direct-order-status",
                trace_path=str(Path(directory) / "d.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("dir"))
            agent = await run_scenario_case(
                mode="agent", case_id="agent-delayed-shipment",
                trace_path=str(Path(directory) / "a.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("agt"))
        self.assertEqual(direct.attribution, {
            "steps": [{"step_name": "tool.lookup_order", "latency_ms": 8, "cost_cents": 1, "attempts": 1}],
            "totals": {"latency_ms": 8, "cost_cents": 1, "attempts": 1}})
        self.assertEqual(agent.attribution, {
            "steps": [
                {"step_name": "model", "latency_ms": 90, "cost_cents": 6, "attempts": 3},
                {"step_name": "tool.lookup_order", "latency_ms": 8, "cost_cents": 1, "attempts": 1},
                {"step_name": "tool.lookup_shipment", "latency_ms": 9, "cost_cents": 1, "attempts": 1}],
            "totals": {"latency_ms": 107, "cost_cents": 8, "attempts": 5}})

    async def test_attribution_absent_rejected_by_schema(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(RESULT_SCHEMA)
        with tempfile.TemporaryDirectory() as directory:
            result = await run_scenario_case(
                mode="direct", case_id="direct-order-status",
                trace_path=str(Path(directory) / "t.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("absent"))
        stripped = {key: value for key, value in result.to_dict().items() if key != "attribution"}
        self.assertTrue(validator.is_valid(result.to_dict()))
        self.assertFalse(validator.is_valid(stripped))
