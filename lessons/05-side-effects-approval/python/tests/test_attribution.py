import json
import unittest
from pathlib import Path
import tempfile

from boundrelay_m5.executor import CrashSignal
from boundrelay_m5.runner import run_case

ROOT = Path(__file__).resolve().parents[4]
RESULT_SCHEMA = json.loads((ROOT / "contracts/results/order-closure-result.schema.json").read_text(encoding="utf-8"))
WORKER_STEPS = [
    {'step_name': 'worker.order-details', 'latency_ms': 10, 'cost_cents': 0, 'attempts': 1},
    {'step_name': 'worker.payment-status', 'latency_ms': 11, 'cost_cents': 0, 'attempts': 1},
    {'step_name': 'worker.delivery-status', 'latency_ms': 12, 'cost_cents': 0, 'attempts': 1}]


class AttributionProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_approval_omits_the_effect_step_record(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            result = await run_case(case_id='approval-rejected-no-effect',
                                    trace_path=str(Path(directory) / 't.jsonl'),
                                    state_dir=str(Path(directory) / 'state'))
        self.assertEqual(result['attribution'], {
            'steps': WORKER_STEPS,
            'totals': {'latency_ms': 33, 'cost_cents': 0, 'attempts': 3}})

    async def test_submit_window_resume_counts_the_original_attempt_once(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            def on_crash():
                raise CrashSignal('crash')
            with self.assertRaises(CrashSignal):
                await run_case(case_id='crash-submit-window-resolved',
                               trace_path=str(Path(directory) / 'crash.jsonl'),
                               state_dir=str(Path(directory) / 'state'), on_crash=on_crash)
            result = await run_case(case_id='crash-submit-window-resolved',
                                    trace_path=str(Path(directory) / 'resume.jsonl'),
                                    state_dir=str(Path(directory) / 'state'), resume=True)
        self.assertEqual(result['reconciled'], True)
        self.assertEqual(result['attribution'], {
            'steps': WORKER_STEPS + [
                {'step_name': 'effect.submit', 'latency_ms': 40, 'cost_cents': 25, 'attempts': 1}],
            'totals': {'latency_ms': 73, 'cost_cents': 25, 'attempts': 4}})

    async def test_attribution_absent_rejected_by_schema(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(RESULT_SCHEMA)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            result = await run_case(case_id='approval-granted-effect-once',
                                    trace_path=str(Path(directory) / 't.jsonl'),
                                    state_dir=str(Path(directory) / 'state'))
        self.assertEqual(result['attribution']['totals'],
                         {'latency_ms': 73, 'cost_cents': 25, 'attempts': 4})
        stripped = {key: value for key, value in result.items() if key != 'attribution'}
        self.assertTrue(validator.is_valid(result))
        self.assertFalse(validator.is_valid(stripped))
