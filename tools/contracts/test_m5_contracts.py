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
CASES = ['approval-granted-effect-once', 'approval-rejected-no-effect',
         'retry-before-submit', 'crash-submit-window-resolved',
         'sink-unavailable-unknown', 'duplicate-key-suppressed']
KEY = 'cancel-and-refund:ORD-1001'
DIGEST = 'c' * 64
PAYLOAD = {'operation': 'cancel-and-refund', 'order_id': 'ORD-1001',
           'refund_amount_cents': 4200, 'currency': 'EUR'}
COMPLETED = {'status': 'EFFECT_COMPLETED',
             'outcome': {'refund_id': 'RFL-2001', 'refunded_at': '2026-11-02T10:00:00Z'}}
REJECTED = {'status': 'EFFECT_REJECTED', 'outcome': None, 'reason': 'INVALID_PAYLOAD'}


def validator(relative):
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f'Missing M5 contract: {relative}')
    schema = json.loads(path.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def def_validator(schema, name):
    return Draft202012Validator(schema['$defs'][name])


def outcome(index, failed=False):
    return {'worker_id': IDS[index], 'status': 'FAILED' if failed else 'SUCCEEDED',
            'output': None if failed else deepcopy(OUTPUTS[index]),
            'failure_code': 'WORKER_EXECUTION_FAILED' if failed else None}


def m5_result(status='SUCCEEDED'):
    approval_rejected = status == 'APPROVAL_REJECTED'
    all_failed = status == 'ALL_FAILED'
    partial = status == 'PARTIAL'
    unknown = status == 'UNKNOWN'
    run_status = 'FAILED' if (approval_rejected or all_failed) else status
    workers_failed = (0, 1, 2) if all_failed else ((2,) if partial else ())
    effect_status = ('EFFECT_COMPLETED' if status == 'SUCCEEDED'
                     else ('EFFECT_UNPROVABLE' if unknown else None))
    decision = ('rejected' if approval_rejected
                else ('none' if (all_failed or partial) else 'granted'))
    key = None if (approval_rejected or all_failed or partial) else KEY
    return {'schema_version': '1.0', 'run_id': 'test-run',
            'scenario_id': 'order-closure', 'case_id': 'test-case',
            'execution_mode': 'parallel', 'concurrency_limit': 2,
            'peak_concurrency': 2, 'order_id': 'ORD-1001', 'status': run_status,
            'worker_outcomes': [outcome(i, i in workers_failed) for i in range(3)],
            'synthesis_invoked': False,
            'brief': None,
            'failure_code': ('APPROVAL_REJECTED' if approval_rejected
                             else ('ALL_WORKERS_FAILED' if all_failed else None)),
            'approval_decision': decision, 'effect_status': effect_status,
            'idempotency_key': key, 'reconciled': False,
            'trace_path': 'trace.jsonl', 'resumed': False,
            'restored_cursor': None, 'restored_worker_ids': [],
            'state_dir': 'state',
            'run_state_status': 'UNKNOWN' if unknown else run_status}

class M5ContractsTests(unittest.TestCase):
    def test_six_cases_and_closed_effect_contract(self):
        effect_check = validator('contracts/effects/order-closure-effect.schema.json')
        payload_check = def_validator(effect_check.schema, 'effectPayload')
        self.assertTrue(payload_check.is_valid(PAYLOAD))
        for mutate in [lambda p: p.update(memo='note'),
                       lambda p: p.update(operation='cancel'),
                       lambda p: p.update(order_id='ORD-11'),
                       lambda p: p.update(refund_amount_cents=4300),
                       lambda p: p.update(currency='USD'),
                       lambda p: p.pop('currency')]:
            bad = deepcopy(PAYLOAD)
            mutate(bad)
            self.assertFalse(payload_check.is_valid(bad), bad)
        outcome_check = def_validator(effect_check.schema, 'effectOutcome')
        self.assertTrue(outcome_check.is_valid(COMPLETED))
        self.assertTrue(outcome_check.is_valid(REJECTED))
        bad_outcomes = [{'status': 'EFFECT_COMPLETED', 'outcome': None},
                        {'status': 'EFFECT_COMPLETED',
                         'outcome': {'refund_id': 'RF-1',
                                     'refunded_at': '2026-11-02T10:00:00Z'}},
                        {'status': 'EFFECT_REJECTED', 'outcome': None,
                         'reason': 'OTHER'},
                        {'status': 'EFFECT_REJECTED', 'outcome': {'x': 1},
                         'reason': 'INVALID_PAYLOAD'},
                        {'status': 'EFFECT_COMPLETED',
                         'outcome': {'refund_id': 'RFL-2001'}}]
        for bad in bad_outcomes:
            self.assertFalse(outcome_check.is_valid(bad), bad)
        record = {'key': KEY, 'payload_digest': DIGEST, 'effect': COMPLETED}
        self.assertTrue(effect_check.is_valid(record))
        self.assertTrue(effect_check.is_valid({**record, 'effect': REJECTED}))
        bad_records = [{'key': KEY, 'payload_digest': 'C' * 64, 'effect': COMPLETED},
                       {'key': KEY, 'payload_digest': 'nothex', 'effect': COMPLETED},
                       {'key': KEY, 'payload_digest': 'c' * 63, 'effect': COMPLETED},
                       {'key': '', 'payload_digest': DIGEST, 'effect': COMPLETED},
                       {**record, 'extra': 1},
                       {**record, 'status': 'EFFECT_COMPLETED'},
                       {'key': KEY, 'payload_digest': DIGEST},
                       {'key': KEY, 'payload_digest': 7, 'effect': COMPLETED}]
        for bad in bad_records:
            self.assertFalse(effect_check.is_valid(bad), bad)
        audit_check = validator('contracts/audit/order-closure-audit.schema.json')
        approval_ok = {'kind': 'approval', 'operation': 'cancel-and-refund',
                       'order_id': 'ORD-1001', 'payload_digest': DIGEST,
                       'decision': 'granted', 'approver': 'approver-primary'}
        effect_ok = {'kind': 'effect', 'operation': 'cancel-and-refund',
                     'order_id': 'ORD-1001', 'idempotency_key': KEY,
                     'effect_status': 'EFFECT_COMPLETED', 'duplicate': False}
        self.assertTrue(audit_check.is_valid(approval_ok))
        self.assertTrue(audit_check.is_valid({**approval_ok, 'decision': 'rejected'}))
        self.assertTrue(audit_check.is_valid(
            {**effect_ok, 'effect_status': 'EFFECT_UNPROVABLE'}))
        bad_audits = [{**approval_ok, 'decision': 'approved'},
                      {**approval_ok, 'approver': ''},
                      {**approval_ok, 'payload_digest': 'zz'},
                      {**approval_ok, 'extra': 1},
                      {**approval_ok, 'idempotency_key': KEY},
                      {**effect_ok, 'effect_status': 'EFFECT_LANDED'},
                      {**effect_ok, 'duplicate': 'no'},
                      {**effect_ok, 'payload_digest': DIGEST},
                      {'kind': 'approval', 'operation': 'cancel-and-refund',
                       'order_id': 'ORD-1001', 'payload_digest': DIGEST,
                       'decision': 'granted'}]
        for bad in bad_audits:
            self.assertFalse(audit_check.is_valid(bad), bad)
        scenario = yaml.safe_load(
            (ROOT / 'fixtures/scenarios/order-closure.yaml').read_text())
        self.assertEqual(scenario['schema_version'], '1.0')
        self.assertEqual(scenario['scenario_id'], 'order-closure')
        self.assertEqual(scenario['order_id'], 'ORD-1001')
        cases = scenario['cases']
        self.assertEqual([c['case_id'] for c in cases], CASES)
        self.assertEqual(len({c['case_id'] for c in cases}), 6)
        controls = {'retry-before-submit': {'crash_before_submit': True},
                    'crash-submit-window-resolved': {'crash_in_submit_window': True},
                    'sink-unavailable-unknown': {'crash_in_submit_window': True,
                                                 'sink_unavailable': True}}
        for case in cases:
            self.assertEqual(case['execution_mode'], 'parallel')
            self.assertEqual(case['completion_order'], IDS)
            self.assertEqual(case['worker_fixture'],
                             'fixtures/workers/order-brief/complete.yaml')
            fixture = yaml.safe_load((ROOT / case['worker_fixture']).read_text())
            self.assertEqual(sorted(fixture), sorted(IDS))
            self.assertEqual(case['approval']['approver'], 'approver-primary')
            expected = 'rejected' if case['case_id'] == 'approval-rejected-no-effect' \
                else 'granted'
            self.assertEqual(case['approval']['decision'], expected)
            if case['case_id'] in controls:
                self.assertEqual(case['controls'], controls[case['case_id']])
            else:
                self.assertNotIn('controls', case)
            if case['case_id'] == 'duplicate-key-suppressed':
                self.assertTrue(case['duplicate_key'])
            else:
                self.assertNotIn('duplicate_key', case)
        catalog = yaml.safe_load(
            (ROOT / 'lessons/05-side-effects-approval/invariants.yaml').read_text())
        self.assertEqual(catalog['scenario_id'], 'order-closure')
        self.assertEqual([v['id'] for v in catalog['invariants']],
                         [f'M5-{i:02}' for i in range(1, 21)])
    def test_result_status_count_policy(self):
        check = validator('contracts/results/order-closure-result.schema.json')
        for status in ['SUCCEEDED', 'APPROVAL_REJECTED', 'UNKNOWN',
                       'ALL_FAILED', 'PARTIAL']:
            self.assertTrue(check.is_valid(m5_result(status)), status)
        reconciled = m5_result('SUCCEEDED')
        reconciled['reconciled'] = True
        self.assertTrue(check.is_valid(reconciled))
        negatives = []
        unknown = m5_result('UNKNOWN')
        unknown['failure_code'] = 'ALL_WORKERS_FAILED'
        negatives.append(unknown)
        unknown = m5_result('UNKNOWN')
        unknown['effect_status'] = 'EFFECT_COMPLETED'
        negatives.append(unknown)
        unknown = m5_result('UNKNOWN')
        unknown['idempotency_key'] = None
        negatives.append(unknown)
        partial = m5_result('PARTIAL')
        partial['reconciled'] = True
        negatives.append(partial)
        granted = m5_result('SUCCEEDED')
        granted['effect_status'] = None
        negatives.append(granted)
        granted = m5_result('SUCCEEDED')
        granted['approval_decision'] = 'none'
        negatives.append(granted)
        for field in ['reconciled', 'approval_decision', 'idempotency_key',
                      'effect_status', 'synthesis_invoked', 'trace_path']:
            stale = m5_result('SUCCEEDED')
            del stale[field]
            negatives.append(stale)
        extras = m5_result('SUCCEEDED')
        extras['extra_key'] = 1
        negatives.append(extras)
        extras = m5_result('SUCCEEDED')
        extras['payload_digest'] = DIGEST
        negatives.append(extras)
        extras = m5_result('UNKNOWN')
        extras['approval_digest'] = DIGEST
        negatives.append(extras)
        for invalid in negatives:
            self.assertFalse(check.is_valid(invalid), invalid)


if __name__ == '__main__':
    unittest.main()
