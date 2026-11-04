import json
import unittest
from pathlib import Path
import tempfile

from boundrelay_m0.runner import run_scenario_case

ROOT = Path(__file__).resolve().parents[4]
RESULT_SCHEMA = json.loads((ROOT / "contracts/results/run-result.schema.json").read_text(encoding="utf-8"))


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


class AttributionProbeTests(unittest.TestCase):
    def test_attribution_present_and_sums_match(self):
        with tempfile.TemporaryDirectory() as directory:
            deterministic = run_scenario_case(
                mode="deterministic", case_id="billing-duplicate-charge",
                trace_path=str(Path(directory) / "d.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("det"))
            model = run_scenario_case(
                mode="model", case_id="billing-duplicate-charge",
                trace_path=str(Path(directory) / "m.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("mod"))
        self.assertEqual(deterministic.attribution, {
            "steps": [
                {"step_name": "classify", "latency_ms": 30, "cost_cents": 0, "attempts": 1},
                {"step_name": "specialist.billing", "latency_ms": 10, "cost_cents": 0, "attempts": 1}],
            "totals": {"latency_ms": 40, "cost_cents": 0, "attempts": 2}})
        self.assertEqual(model.attribution["steps"][0],
                         {"step_name": "classify", "latency_ms": 30, "cost_cents": 2, "attempts": 1})
        self.assertEqual(model.attribution["totals"],
                         {"latency_ms": 40, "cost_cents": 2, "attempts": 2})

    def test_attribution_absent_rejected_by_schema(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(RESULT_SCHEMA)
        with tempfile.TemporaryDirectory() as directory:
            result = run_scenario_case(
                mode="model", case_id="billing-duplicate-charge",
                trace_path=str(Path(directory) / "t.jsonl"),
                clock=fixed_clock, id_factory=fixed_ids("absent"))
        stripped = {key: value for key, value in result.to_dict().items() if key != "attribution"}
        self.assertTrue(validator.is_valid(result.to_dict()))
        self.assertFalse(validator.is_valid(stripped))
