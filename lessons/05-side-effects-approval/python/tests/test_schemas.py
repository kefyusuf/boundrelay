import unittest
from boundrelay_m5.schemas import (validate_worker_output,validate_run_result,
    validate_run_state_document,validate_effect_payload,validate_effect_record,
    validate_audit_record,canonical_state_body,state_digest)
BASE={'state_schema_version':'1.0','run_id':'r1','scenario_id':'order-closure','case_id':'c','execution_mode':'parallel','concurrency_limit':2,'requested_order_id':'ORD-1001','status':'RUNNING','steps':[
    {'worker_id':'order-details','status':'PENDING','output':None,'failure_code':None},
    {'worker_id':'payment-status','status':'PENDING','output':None,'failure_code':None},
    {'worker_id':'delivery-status','status':'PENDING','output':None,'failure_code':None}],'sequence_cursor':0}
IDS=('order-details','payment-status','delivery-status')
OUTPUTS=({'order_id':'ORD-1001','order_status':'SHIPPED'},{'order_id':'ORD-1001','payment_status':'PAID'},{'order_id':'ORD-1001','delivery_status':'DELAYED'})
def outcome(index,failed=False):
    if failed:return {'worker_id':IDS[index],'status':'FAILED','output':None,'failure_code':'WORKER_EXECUTION_FAILED'}
    return {'worker_id':IDS[index],'status':'SUCCEEDED','output':dict(OUTPUTS[index]),'failure_code':None}
def result():
    return {'schema_version':'1.0','run_id':'r1','scenario_id':'order-closure','case_id':'c','execution_mode':'parallel','concurrency_limit':2,'peak_concurrency':2,'order_id':'ORD-1001','status':'SUCCEEDED','worker_outcomes':[outcome(0),outcome(1),outcome(2)],'synthesis_invoked':False,'brief':None,'failure_code':None,'approval_decision':'granted','effect_status':'EFFECT_COMPLETED','idempotency_key':'cancel-and-refund:ORD-1001','reconciled':False,'trace_path':'t.jsonl','resumed':False,'restored_cursor':None,'restored_worker_ids':[],'state_dir':'state','run_state_status':'SUCCEEDED'}
class SchemaTests(unittest.TestCase):
    def test_reject_original_invalid_output(self):
        valid={'order_id':'ORD-1001','payment_status':'PAID'}
        accepted=validate_worker_output('payment-status',valid,'ORD-1001')
        self.assertTrue(accepted.valid);self.assertEqual(accepted.value,valid)
        cycle={};cycle['self']=cycle
        for raw in [{**valid,'private':'secret'},{**valid,'order_id':'ORD-9999'},{**valid,'payment_status':'UNKNOWN'},float('nan'),float('inf'),cycle,{**valid,'n':10**10000}]:
            rejected=validate_worker_output('payment-status',raw,'ORD-1001')
            self.assertFalse(rejected.valid);self.assertIsNone(rejected.value)
    def test_validate_run_state_document_enforces_closed_m5_schema(self):
        doc={**BASE,'digest':state_digest(canonical_state_body(BASE))}
        self.assertTrue(validate_run_state_document(doc).valid)
        self.assertFalse(validate_run_state_document({**doc,'extra':1}).valid)
        self.assertFalse(validate_run_state_document({**doc,'digest':'zz'}).valid)
        self.assertFalse(validate_run_state_document({**doc,'steps':doc['steps'][:2]}).valid)
        self.assertFalse(validate_run_state_document({**doc,'scenario_id':'order-brief-recovery'}).valid)
        self.assertTrue(validate_run_state_document({**doc,'status':'UNKNOWN'}).valid)
    def test_validate_run_result_uses_m5_schema_with_effect_fields(self):
        good=result()
        self.assertTrue(validate_run_result(good))
        self.assertTrue(validate_run_result({**good,'reconciled':True}))
        unknown={**good,'status':'UNKNOWN','failure_code':None,'approval_decision':'granted','effect_status':'EFFECT_UNPROVABLE','reconciled':False,'run_state_status':'UNKNOWN'}
        self.assertTrue(validate_run_result(unknown))
        bad_unknown={**unknown,'effect_status':'EFFECT_COMPLETED'}
        self.assertFalse(validate_run_result(bad_unknown))
        bad_unknown2={**unknown,'failure_code':'ALL_WORKERS_FAILED'}
        self.assertFalse(validate_run_result(bad_unknown2))
        bad_partial={**good,'status':'PARTIAL','reconciled':True,'approval_decision':'none','effect_status':None,'idempotency_key':None,'run_state_status':'PARTIAL'}
        self.assertFalse(validate_run_result(bad_partial))
        self.assertFalse(validate_run_result({**good,'extra':1}))
        self.assertFalse(validate_run_result({**good,'synthesis_invoked':True}))
    def test_effect_payload_and_ledger_records_validate_against_closed_schema(self):
        payload={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
        self.assertTrue(validate_effect_payload(payload).valid)
        self.assertFalse(validate_effect_payload({**payload,'refund_amount_cents':4300}).valid)
        self.assertFalse(validate_effect_payload({**payload,'memo':'x'}).valid)
        completed={'status':'EFFECT_COMPLETED','outcome':{'refund_id':'RFL-1001','refunded_at':'2026-11-02T00:00:00Z'}}
        record={'key':'cancel-and-refund:ORD-1001','payload_digest':'c'*64,'effect':completed}
        self.assertTrue(validate_effect_record(record).valid)
        self.assertFalse(validate_effect_record({**record,'payload_digest':'C'*64}).valid)
        self.assertFalse(validate_effect_record({**record,'extra':1}).valid)
        self.assertFalse(validate_effect_record({'key':'k','payload_digest':'c'*64}).valid)
    def test_audit_records_validate_against_the_closed_oneof_schema(self):
        approval={'kind':'approval','operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':'c'*64,'decision':'granted','approver':'approver-primary'}
        effect={'kind':'effect','operation':'cancel-and-refund','order_id':'ORD-1001','idempotency_key':'cancel-and-refund:ORD-1001','effect_status':'EFFECT_COMPLETED','duplicate':False}
        self.assertTrue(validate_audit_record(approval))
        self.assertTrue(validate_audit_record(effect))
        self.assertFalse(validate_audit_record({**approval,'idempotency_key':'x'}))
        self.assertFalse(validate_audit_record({**effect,'payload_digest':'c'*64}))
        self.assertFalse(validate_audit_record({**approval,'decision':'approved'}))
    def test_canonical_body_and_digest_rules_unchanged_from_m4(self):
        self.assertEqual(canonical_state_body({'digest':'ignored','b':2,'a':1}),'{"a":1,"b":2}')
        self.assertEqual(state_digest('{"a":1}'),state_digest('{"a":1}'))



