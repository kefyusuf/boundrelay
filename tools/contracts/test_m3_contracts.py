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


def validator(relative):
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f'Missing M3 contract: {relative}')
    schema = json.loads(path.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def outcome(index, failed=False):
    return {'worker_id': IDS[index], 'status': 'FAILED' if failed else 'SUCCEEDED',
            'output': None if failed else deepcopy(OUTPUTS[index]),
            'failure_code': 'WORKER_EXECUTION_FAILED' if failed else None}


def result(failed=()):
    return {'schema_version': '1.0', 'run_id': 'test-run', 'scenario_id': 'order-brief',
            'case_id': 'test-case', 'execution_mode': 'parallel', 'concurrency_limit': 2,
            'peak_concurrency': 2, 'order_id': 'ORD-1001',
            'status': 'FAILED' if len(failed) == 3 else 'PARTIAL' if failed else 'SUCCEEDED',
            'worker_outcomes': [outcome(i, i in failed) for i in range(3)],
            'synthesis_invoked': len(failed) < 3,
            'brief': None if len(failed) == 3 else {
                'order_id': 'ORD-1001', 'sections': [
                    {'worker_id': IDS[i], 'output': deepcopy(OUTPUTS[i])} for i in range(3) if i not in failed],
                'missing_workers': [IDS[i] for i in failed], 'complete': not failed},
            'failure_code': 'ALL_WORKERS_FAILED' if len(failed) == 3 else None,
            'trace_path': 'trace.jsonl'}


class M3ContractsTests(unittest.TestCase):
    def test_six_cases_and_closed_worker_contract(self):
        check = validator('contracts/workers/order-brief-worker-result.schema.json')
        for i in range(3):
            success = outcome(i)
            self.assertTrue(check.is_valid(success))
            self.assertTrue(check.is_valid(outcome(i, True)))
            for invalid in [{**success, 'private_note': 'secret'},
                            {**success, 'failure_code': 'WORKER_EXECUTION_FAILED'},
                            {**success, 'worker_id': 'unknown'},
                            {**success, 'output': OUTPUTS[(i + 1) % 3]},
                            {**success, 'output': {**OUTPUTS[i], 'order_id': 'bad'}},
                            {**success, 'output': {**OUTPUTS[i], 'private': 'secret'}},
                            {**outcome(i, True), 'failure_code': 'OTHER'}]:
                self.assertFalse(check.is_valid(invalid), invalid)
        scenario = yaml.safe_load((ROOT / 'fixtures/scenarios/order-brief.yaml').read_text())
        cases = scenario['cases']
        self.assertEqual(scenario['schema_version'], '1.0')
        self.assertEqual(scenario['order_id'], 'ORD-1001')
        self.assertEqual([c['case_id'] for c in cases], [
            'sequential-complete', 'parallel-complete', 'parallel-out-of-order',
            'parallel-partial-failure', 'parallel-all-failed', 'parallel-invalid-output'])
        self.assertEqual(len({c['case_id'] for c in cases}), 6)
        for case in cases:
            fixture = yaml.safe_load((ROOT / case['worker_fixture']).read_text())
            self.assertEqual(list(fixture), IDS)
            self.assertEqual(sorted(case['completion_order']), sorted(IDS))
            for i, worker_id in enumerate(IDS):
                instruction = fixture[worker_id]
                self.assertIn(instruction['operation'], ('return', 'raise'))
                if instruction['operation'] == 'return':
                    self.assertEqual(check.is_valid({**outcome(i), 'output': instruction['output']}),
                                     not (case['case_id'] == 'parallel-invalid-output' and i == 1))
        catalog = yaml.safe_load((ROOT / 'lessons/03-parallel-fanout-fanin/invariants.yaml').read_text())
        self.assertEqual([v['id'] for v in catalog['invariants']], [f'M3-{i:02}' for i in range(1, 21)])

    def test_result_status_count_policy(self):
        check = validator('contracts/results/order-brief-result.schema.json')
        for failed in [(), (2,), (1, 2), (0, 1, 2)]:
            self.assertTrue(check.is_valid(result(failed)))
        invalid = result((2,))
        invalid['brief']['complete'] = True
        self.assertFalse(check.is_valid(invalid))
        invalid = result((0, 1, 2))
        invalid['brief'] = result()['brief']
        self.assertFalse(check.is_valid(invalid))
        for mutate in [lambda r: r.update(status='SUCCEEDED'),
                       lambda r: r.update(synthesis_invoked=False),
                       lambda r: r.update(concurrency_limit=3),
                       lambda r: r.update(worker_outcomes=[outcome(0)] * 3),
                       lambda r: r.update(worker_outcomes=[outcome(0)]),
                       lambda r: r.update(private_note='secret'),
                       lambda r: r['brief'].update(sections=[])]:
            invalid = result((2,))
            mutate(invalid)
            self.assertFalse(check.is_valid(invalid), invalid)


if __name__ == '__main__':
    unittest.main()
