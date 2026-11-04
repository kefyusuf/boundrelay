import json
import unittest
from pathlib import Path
import tempfile

from boundrelay_m2.runner import run_scenario_case

ROOT = Path(__file__).resolve().parents[4]
RESULT_SCHEMA = json.loads((ROOT / "contracts/results/handoff-result.schema.json").read_text(encoding="utf-8"))


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
            code = await run_scenario_case(
                mode="code", case_id="code-billing-handoff",
                trace_path=str(Path(directory) / "c.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("code"))
            model = await run_scenario_case(
                mode="model", case_id="model-technical-handoff",
                trace_path=str(Path(directory) / "m.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("mod"))
        self.assertEqual(code.attribution, {
            "steps": [
                {"step_name": "classify", "latency_ms": 30, "cost_cents": 0, "attempts": 1},
                {"step_name": "receiver.billing-specialist", "latency_ms": 10, "cost_cents": 0, "attempts": 1}],
            "totals": {"latency_ms": 40, "cost_cents": 0, "attempts": 2}})
        self.assertEqual(model.attribution, {
            "steps": [
                {"step_name": "classify", "latency_ms": 30, "cost_cents": 2, "attempts": 1},
                {"step_name": "receiver.technical-specialist", "latency_ms": 11, "cost_cents": 0, "attempts": 1}],
            "totals": {"latency_ms": 41, "cost_cents": 2, "attempts": 2}})

    async def test_attribution_absent_rejected_by_schema(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(RESULT_SCHEMA)
        with tempfile.TemporaryDirectory() as directory:
            result = await run_scenario_case(
                mode="code", case_id="code-billing-handoff",
                trace_path=str(Path(directory) / "t.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("absent"))
        stripped = {key: value for key, value in result.to_dict().items() if key != "attribution"}
        self.assertTrue(validator.is_valid(result.to_dict()))
        self.assertFalse(validator.is_valid(stripped))
