from copy import deepcopy
import json
from pathlib import Path
import unittest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
IDS = ['order-details', 'payment-status', 'delivery-status']
OUTPUTS = [{'order_id': 'ORD-1001', 'order_status': 'SHIPPED'},
           {'order_id': 'ORD-1001', 'payment_status': 'PAID'},
           {'order_id': 'ORD-1001', 'delivery_status': 'DELAYED'}]
HEX = 'a' * 64


def validator(relative):
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f'Missing M4 contract: {relative}')
    schema = json.loads(path.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def step(index, status='SUCCEEDED'):
    if status == 'SUCCEEDED':
        return {'worker_id': IDS[index], 'status': 'SUCCEEDED',
                'output': deepcopy(OUTPUTS[index]), 'failure_code': None}
    if status == 'FAILED':
        return {'worker_id': IDS[index], 'status': 'FAILED', 'output': None,
                'failure_code': 'WORKER_EXECUTION_FAILED'}
    return {'worker_id': IDS[index], 'status': status, 'output': None, 'failure_code': None}


def outcome(index, failed=False):
    return {'worker_id': IDS[index], 'status': 'FAILED' if failed else 'SUCCEEDED',
            'output': None if failed else deepcopy(OUTPUTS[index]),
            'failure_code': 'WORKER_EXECUTION_FAILED' if failed else None}


def state_doc(status='RUNNING', step_statuses=('SUCCEEDED', 'SUCCEEDED', 'PENDING'), cursor=2):
    return {'state_schema_version': '1.0', 'run_id': 'test-run',
            'scenario_id': 'order-brief-recovery', 'case_id': 'parallel-clean-complete',
            'execution_mode': 'parallel', 'concurrency_limit': 2,
            'requested_order_id': 'ORD-1001', 'status': status,
            'steps': [step(i, step_statuses[i]) for i in range(3)],
            'sequence_cursor': cursor, 'digest': HEX}


def result(failed=(), cancelled=False, resumed=False):
    status = 'CANCELLED' if cancelled else ('FAILED' if len(failed) == 3 else 'PARTIAL' if failed else 'SUCCEEDED')
    outcomes = ([outcome(i) for i in range(2)] if cancelled
                else [outcome(i, i in failed) for i in range(3)])
    return {'schema_version': '1.0', 'run_id': 'test-run', 'scenario_id': 'order-brief-recovery',
            'case_id': 'test-case', 'execution_mode': 'parallel', 'concurrency_limit': 2,
            'peak_concurrency': 2, 'order_id': 'ORD-1001', 'status': status,
            'worker_outcomes': outcomes,
            'synthesis_invoked': False if cancelled else len(failed) < 3,
            'brief': None if (cancelled or len(failed) == 3) else {
                'order_id': 'ORD-1001', 'sections': [
                    {'worker_id': IDS[i], 'output': deepcopy(OUTPUTS[i])}
                    for i in range(3) if i not in failed],
                'missing_workers': [IDS[i] for i in failed], 'complete': not failed},
            'failure_code': 'ALL_WORKERS_FAILED' if len(failed) == 3 else None,
            'trace_path': 'trace.jsonl', 'resumed': resumed,
            'restored_cursor': 1 if resumed else None,
            'restored_worker_ids': ['order-details'] if resumed else [],
            'state_dir': 'state', 'run_state_status': status}


class M4ContractsTests(unittest.TestCase):
    def test_six_cases_and_closed_state_contract(self):
        state_check = validator('contracts/state/order-brief-run-state.schema.json')
        self.assertTrue(state_check.is_valid(state_doc()))
        self.assertTrue(state_check.is_valid(state_doc(status='CANCELLED', step_statuses=(
            'SUCCEEDED', 'SUCCEEDED', 'CANCELLED'))))
        self.assertTrue(state_check.is_valid(state_doc(step_statuses=(
            'SUCCEEDED', 'RUNNING', 'PENDING'))))
        self.assertTrue(state_check.is_valid(state_doc(status='PARTIAL', step_statuses=(
            'SUCCEEDED', 'SUCCEEDED', 'FAILED'))))
        for invalid in [state_doc(status='COMPLETED'),
                        {**state_doc(), 'extra_key': 1},
                        {**state_doc(), 'digest': 'nothex'},
                        {**state_doc(), 'state_schema_version': '2.0'},
                        {**state_doc(), 'scenario_id': 'order-brief'},
                        {**state_doc(), 'requested_order_id': 'bad'},
                        {**state_doc(), 'sequence_cursor': 4},
                        {**state_doc(), 'steps': [step(0)]},
                        {**state_doc(step_statuses=('SUCCEEDED', 'SHIPPED', 'PENDING'))},
                        {**state_doc(), 'steps': [step(0), step(1), {**step(2), 'output': OUTPUTS[0]}]},
                        {**state_doc(step_statuses=('SUCCEEDED', 'SUCCEEDED', 'FAILED')),
                         'steps': [step(0), step(1), step(2, 'FAILED')][:2] + [
                             {**step(2, 'FAILED'), 'failure_code': 'OTHER'}]}]:
            self.assertFalse(state_check.is_valid(invalid), invalid)
        worker_check = validator('contracts/workers/order-brief-worker-result.schema.json')
        for i in range(3):
            self.assertTrue(worker_check.is_valid(outcome(i)))
        scenario = yaml.safe_load((ROOT / 'fixtures/scenarios/order-brief-recovery.yaml').read_text())
        cases = scenario['cases']
        self.assertEqual(scenario['schema_version'], '1.0')
        self.assertEqual(scenario['scenario_id'], 'order-brief-recovery')
        self.assertEqual(scenario['order_id'], 'ORD-1001')
        self.assertEqual([c['case_id'] for c in cases], [
            'parallel-clean-complete', 'parallel-crash-resume', 'parallel-crash-resume-partial',
            'parallel-cancel-resume', 'parallel-replay-from-checkpoint', 'parallel-corrupt-state'])
        self.assertEqual(len({c['case_id'] for c in cases}), 6)
        controls = {'parallel-crash-resume': {'crash_after': 'payment-status'},
                    'parallel-crash-resume-partial': {'crash_after': 'delivery-status'},
                    'parallel-cancel-resume': {'cancel_before': 'delivery-status'}}
        for case in cases:
            self.assertEqual(case['execution_mode'], 'parallel')
            self.assertEqual(sorted(case['completion_order']), sorted(IDS))
            fixture = yaml.safe_load((ROOT / case['worker_fixture']).read_text())
            self.assertEqual(list(fixture), IDS)
            expected_controls = controls.get(case['case_id'])
            if expected_controls:
                self.assertEqual(case['controls'], expected_controls)
            else:
                self.assertNotIn('controls', case)
            if case['case_id'] == 'parallel-replay-from-checkpoint':
                self.assertEqual(case['replay_from_step'], 1)
            if case['case_id'] == 'parallel-corrupt-state':
                self.assertEqual(case['tampered_state'], 'flip_payment_outcome')
        catalog = yaml.safe_load((ROOT / 'lessons/04-durable-state-recovery/invariants.yaml').read_text())
        self.assertEqual([v['id'] for v in catalog['invariants']], [f'M4-{i:02}' for i in range(1, 21)])
        self.assertEqual(catalog['scenario_id'], 'order-brief-recovery')

    def test_result_status_count_policy(self):
        check = validator('contracts/results/order-brief-recovery-result.schema.json')
        for failed in [(), (2,), (1, 2), (0, 1, 2)]:
            self.assertTrue(check.is_valid(result(failed)))
        self.assertTrue(check.is_valid(result(cancelled=True)))
        self.assertTrue(check.is_valid(result(failed=(2,), resumed=True)))
        invalid = result((2,))
        invalid['brief']['complete'] = True
        self.assertFalse(check.is_valid(invalid))
        invalid = result((0, 1, 2))
        invalid['brief'] = result()['brief']
        self.assertFalse(check.is_valid(invalid))
        invalid = result(cancelled=True)
        invalid['failure_code'] = 'ALL_WORKERS_FAILED'
        self.assertFalse(check.is_valid(invalid))
        invalid = result(cancelled=True)
        invalid['synthesis_invoked'] = True
        self.assertFalse(check.is_valid(invalid))
        invalid = result(resumed=True)
        invalid['restored_cursor'] = None
        self.assertFalse(check.is_valid(invalid))
        invalid = result()
        invalid['run_state_status'] = 'PARTIAL'
        self.assertFalse(check.is_valid(invalid))
        for mutate in [lambda r: r.update(status='SUCCEEDED'),
                       lambda r: r.update(synthesis_invoked=False),
                       lambda r: r.update(concurrency_limit=3),
                       lambda r: r.update(worker_outcomes=[outcome(0)] * 3),
                       lambda r: r.update(private_note='secret'),
                       lambda r: r.update(state_schema_version='1.0'),
                       lambda r: r['brief'].update(sections=[])]:
            invalid = result((2,))
            mutate(invalid)
            self.assertFalse(check.is_valid(invalid), invalid)


if __name__ == '__main__':
    unittest.main()
