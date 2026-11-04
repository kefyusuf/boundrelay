import json
import unittest
from pathlib import Path
import tempfile

from boundrelay_m4.executor import CrashSignal
from boundrelay_m4.runner import run_case

ROOT = Path(__file__).resolve().parents[4]
RESULT_SCHEMA = json.loads((ROOT / "contracts/results/order-brief-recovery-result.schema.json").read_text(encoding="utf-8"))


class AttributionProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_crash_resume_reconciles_attempts_across_phases(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            def crash():
                raise CrashSignal('crash')
            with self.assertRaises(CrashSignal):
                await run_case(case_id='parallel-crash-resume',
                               trace_path=str(Path(directory) / 'crash.jsonl'),
                               state_dir=str(Path(directory) / 'state'), on_crash=crash)
            result = await run_case(case_id='parallel-crash-resume',
                                    trace_path=str(Path(directory) / 'resume.jsonl'),
                                    state_dir=str(Path(directory) / 'state'), resume=True)
        # crash_after fires after the worker's outcome is recorded, so the
        # resumed run re-executes only the pending worker: attempts [1,1,1].
        self.assertEqual(result['attribution'], {
            'steps': [
                {'step_name': 'worker.order-details', 'latency_ms': 10, 'cost_cents': 0, 'attempts': 1},
                {'step_name': 'worker.payment-status', 'latency_ms': 11, 'cost_cents': 0, 'attempts': 1},
                {'step_name': 'worker.delivery-status', 'latency_ms': 12, 'cost_cents': 0, 'attempts': 1},
                {'step_name': 'synthesize', 'latency_ms': 15, 'cost_cents': 0, 'attempts': 1}],
            'totals': {'latency_ms': 48, 'cost_cents': 0, 'attempts': 4}})

    async def test_fresh_run_counts_single_attempts_and_schema_rejects_absent_attribution(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(RESULT_SCHEMA)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            result = await run_case(case_id='parallel-clean-complete',
                                    trace_path=str(Path(directory) / 't.jsonl'),
                                    state_dir=str(Path(directory) / 'state'))
        self.assertEqual(result['attribution']['totals'],
                         {'latency_ms': 48, 'cost_cents': 0, 'attempts': 4})
        stripped = {key: value for key, value in result.items() if key != 'attribution'}
        self.assertTrue(validator.is_valid(result))
        self.assertFalse(validator.is_valid(stripped))
