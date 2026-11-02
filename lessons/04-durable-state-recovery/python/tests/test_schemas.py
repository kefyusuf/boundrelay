import unittest
from boundrelay_m4.schemas import validate_worker_output,validate_run_result,validate_run_state_document,canonical_state_body,state_digest
BASE={'state_schema_version':'1.0','run_id':'r1','scenario_id':'order-brief-recovery','case_id':'c','execution_mode':'parallel','concurrency_limit':2,'requested_order_id':'ORD-1001','status':'RUNNING','steps':[
    {'worker_id':'order-details','status':'PENDING','output':None,'failure_code':None},
    {'worker_id':'payment-status','status':'PENDING','output':None,'failure_code':None},
    {'worker_id':'delivery-status','status':'PENDING','output':None,'failure_code':None}],'sequence_cursor':0}
IDS=('order-details','payment-status','delivery-status')
OUTPUTS=({'order_id':'ORD-1001','order_status':'SHIPPED'},{'order_id':'ORD-1001','payment_status':'PAID'},{'order_id':'ORD-1001','delivery_status':'DELIVERED'})
def outcome(index,failed=False):
    if failed:return {'worker_id':IDS[index],'status':'FAILED','output':None,'failure_code':'WORKER_EXECUTION_FAILED'}
    return {'worker_id':IDS[index],'status':'SUCCEEDED','output':dict(OUTPUTS[index]),'failure_code':None}

def result():
    return {'schema_version':'1.0','run_id':'r1','scenario_id':'order-brief-recovery','case_id':'c','execution_mode':'parallel','concurrency_limit':2,'peak_concurrency':2,'order_id':'ORD-1001','status':'SUCCEEDED','worker_outcomes':[outcome(0),outcome(1),outcome(2)],'synthesis_invoked':True,'brief':{'order_id':'ORD-1001','sections':[{'worker_id':IDS[i],'output':dict(OUTPUTS[i])} for i in range(3)],'missing_workers':[],'complete':True},'failure_code':None,'trace_path':'t.jsonl','resumed':False,'restored_cursor':None,'restored_worker_ids':[],'state_dir':'state','run_state_status':'SUCCEEDED'}

class SchemaTests(unittest.TestCase):
    def test_reject_original_invalid_output(self):
        valid={'order_id':'ORD-1001','payment_status':'PAID'}
        accepted=validate_worker_output('payment-status',valid,'ORD-1001')
        self.assertTrue(accepted.valid);self.assertEqual(accepted.value,valid)
        cycle={};cycle['self']=cycle
        for raw in [{**valid,'private':'secret'},{**valid,'order_id':'ORD-9999'},{**valid,'payment_status':'UNKNOWN'},float('nan'),float('inf'),cycle,{**valid,'n':10**10000}]:
            rejected=validate_worker_output('payment-status',raw,'ORD-1001')
            self.assertFalse(rejected.valid);self.assertIsNone(rejected.value)
    def test_validate_run_state_document_enforces_closed_schema(self):
        doc={**BASE,'digest':state_digest(canonical_state_body(BASE))}
        self.assertTrue(validate_run_state_document(doc).valid)
        self.assertFalse(validate_run_state_document({**doc,'extra':1}).valid)
        self.assertFalse(validate_run_state_document({**doc,'digest':'zz'}).valid)
        self.assertFalse(validate_run_state_document({**doc,'steps':doc['steps'][:2]}).valid)
    def test_validate_run_result_uses_recovery_schema_and_canonical_body_rules(self):
        good=result()
        self.assertTrue(validate_run_result(good))
        cancelled={**good,'status':'CANCELLED','synthesis_invoked':False,'brief':None,'failure_code':'ALL_WORKERS_FAILED','run_state_status':'CANCELLED'}
        self.assertFalse(validate_run_result(cancelled))
        self.assertFalse(validate_run_result({**good,'resumed':True}))
        self.assertEqual(canonical_state_body({**good,'digest':'x'}),canonical_state_body(good))
        self.assertEqual(state_digest('{"a":1}'),state_digest('{"a":1}'))
        self.assertEqual(canonical_state_body({'digest':'ignored','b':2,'a':1}),'{"a":1,"b":2}')


