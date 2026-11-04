import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from boundrelay_m5.runner import run_case
from boundrelay_m5.executor import CrashSignal
from boundrelay_m5.state_store import load_run_state
from boundrelay_m5.effect_ledger import EffectLedger
from boundrelay_m5.audit import AuditWriter
from boundrelay_m5.idempotency import effect_digest,effect_key
from boundrelay_m5.scenario import load_scenario
from boundrelay_m5.scripted_workers import ScriptedWorkers
from boundrelay_m5.workers import create_worker_directory
from boundrelay_m5.types import StateBinding,WorkerDefinition

PAYLOAD={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
KEY=effect_key(PAYLOAD)
DIGEST=effect_digest(PAYLOAD)
BINDING=StateBinding(case_id='approval-granted-effect-once',execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

def binding_for(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

def events(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]

class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self,case_id):
        s=load_scenario();spec=next(c for c in s.cases if c.case_id==case_id);p=ScriptedWorkers(spec,s.order_id)
        return p,create_worker_directory(p)
    def wrap_gate(self,d,worker_id,mutate=None):
        original=d.resolve
        def resolve(i):
            w=original(i)
            async def handle(input):
                value=await w.handle(input)
                if i==worker_id and mutate is not None:value=mutate(value)
                return value
            return WorkerDefinition(i,handle)
        d.resolve=resolve
    async def test_granted_run_emits_approval_and_tool_events_in_order(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path=str(Path(tmp)/'run.jsonl');state_dir=str(Path(tmp)/'state')
            result=await run_case(case_id='approval-granted-effect-once',trace_path=path,state_dir=state_dir)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertIsNone(result['failure_code'])
            self.assertEqual(result['approval_decision'],'granted');self.assertEqual(result['effect_status'],'EFFECT_COMPLETED')
            self.assertEqual(result['idempotency_key'],KEY);self.assertFalse(result['reconciled'])
            self.assertFalse(result['synthesis_invoked']);self.assertIsNone(result['brief'])
            self.assertFalse(result['resumed']);self.assertIsNone(result['restored_cursor'])
            self.assertEqual(result['run_state_status'],'SUCCEEDED');self.assertEqual(result['peak_concurrency'],2)
            listed=events(path)
            self.assertEqual(listed[0]['type'],'run.created');self.assertEqual(listed[1]['type'],'run.started')
            self.assertEqual(listed[0]['data'],{'scenario_id':'order-closure','case_id':'approval-granted-effect-once','execution_mode':'parallel','order_id':'ORD-1001','concurrency_limit':2,'state_dir':state_dir})
            approval=[e for e in listed if e['type'].startswith('approval.')]
            self.assertEqual([e['type'] for e in approval],['approval.requested','approval.granted'])
            self.assertEqual(approval[0]['data'],{'operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':DIGEST})
            tool=[e for e in listed if e['type'].startswith('tool.')]
            self.assertEqual([e['type'] for e in tool],['tool.requested','tool.completed'])
            self.assertEqual(tool[0]['data'],{'key':KEY,'payload_digest':DIGEST,'side_effect_class':'external'})
            self.assertEqual(tool[1]['data'],{'key':KEY,'status':'EFFECT_COMPLETED','duplicate':False})
            order=[e['type'] for e in listed]
            self.assertLess(order.index('approval.granted'),order.index('tool.requested'))
            self.assertLess(order.index('tool.completed'),order.index('run.completed'))
            terminal=listed[-1]
            self.assertEqual(terminal['type'],'run.completed')
            self.assertEqual(terminal['data'],{'status':'SUCCEEDED','worker_outcomes':result['worker_outcomes'],'synthesis_invoked':False,'brief':None,'failure_code':None,'peak_concurrency':2,'reconciled':False,'approval_decision':'granted','effect_status':'EFFECT_COMPLETED','idempotency_key':KEY})
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
    async def test_rejected_run_has_zero_submissions_and_records_rejection(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path=str(Path(tmp)/'rejected.jsonl');state_dir=str(Path(tmp)/'state')
            result=await run_case(case_id='approval-rejected-no-effect',trace_path=path,state_dir=state_dir)
            self.assertEqual(result['status'],'FAILED');self.assertEqual(result['failure_code'],'APPROVAL_REJECTED')
            self.assertEqual(result['approval_decision'],'rejected');self.assertIsNone(result['effect_status'])
            self.assertIsNone(result['idempotency_key']);self.assertFalse(result['reconciled'])
            self.assertEqual(EffectLedger(state_dir).records(),[])
            audit=AuditWriter(state_dir).records()
            self.assertEqual(audit,[{'kind':'approval','operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':DIGEST,'decision':'rejected','approver':'approver-primary'}])
            listed=events(path)
            self.assertEqual([e for e in listed if e['type'].startswith('tool.')],[])
            self.assertEqual([e['type'] for e in listed if e['type'].startswith('approval.')],['approval.requested','approval.rejected'])
            self.assertEqual(listed[-1]['type'],'run.failed')
            document=load_run_state(state_dir,binding_for('approval-rejected-no-effect'))['document']
            self.assertEqual(document['status'],'FAILED');self.assertIsNone(document['submit_marker'])
    async def test_failed_reads_stop_before_approval_events(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            p,d=self.fixture('approval-granted-effect-once')
            self.wrap_gate(d,'payment-status',mutate=lambda value:{**value,'private':'PRIVATE-PAYLOAD'})
            path=str(Path(tmp)/'partial.jsonl');state_dir=str(Path(tmp)/'state')
            result=await run_case(case_id='approval-granted-effect-once',trace_path=path,state_dir=state_dir,directory=d,control=p)
            self.assertEqual(result['status'],'PARTIAL');self.assertIsNone(result['failure_code'])
            self.assertEqual(result['approval_decision'],'none');self.assertIsNone(result['effect_status'])
            self.assertIsNone(result['idempotency_key']);self.assertFalse(result['reconciled'])
            listed=events(path)
            self.assertEqual([e for e in listed if e['type'].startswith('approval.')],[])
            self.assertEqual([e for e in listed if e['type'].startswith('tool.')],[])
            self.assertNotIn('PRIVATE-PAYLOAD',Path(path).read_text(encoding='utf-8'))
            self.assertEqual(EffectLedger(state_dir).records(),[])
    async def test_crash_phase_flushes_prefix_without_terminal(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path=str(Path(tmp)/'crash.jsonl');state_dir=str(Path(tmp)/'state');crashes=[]
            def on_crash():
                crashes.append(1);raise CrashSignal('crash')
            with self.assertRaises(CrashSignal):
                await run_case(case_id='crash-submit-window-resolved',trace_path=path,state_dir=state_dir,on_crash=on_crash)
            self.assertEqual(len(crashes),1)
            listed=events(path)
            self.assertEqual(listed[0]['type'],'run.created')
            self.assertTrue(any(e['type']=='tool.requested' for e in listed))
            self.assertFalse(any(e['type']=='tool.completed' for e in listed))
            self.assertFalse(any(e['type'] in ('run.completed','run.failed') for e in listed))
            document=load_run_state(state_dir,binding_for('crash-submit-window-resolved'))['document']
            self.assertEqual(document['status'],'RUNNING')
            self.assertEqual(document['submit_marker'],{'key':KEY,'payload_digest':DIGEST})
            self.assertIsNone(document['effect'])
    async def test_resume_completes_with_reconciled_adoption(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state')
            def on_crash():raise CrashSignal('crash')
            with self.assertRaises(CrashSignal):
                await run_case(case_id='crash-submit-window-resolved',trace_path=str(Path(tmp)/'crash.jsonl'),state_dir=state_dir,on_crash=on_crash)
            result=await run_case(case_id='crash-submit-window-resolved',trace_path=str(Path(tmp)/'resume.jsonl'),state_dir=state_dir,resume=True)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertTrue(result['reconciled'])
            self.assertEqual(result['approval_decision'],'granted');self.assertEqual(result['effect_status'],'EFFECT_COMPLETED')
            self.assertEqual(result['idempotency_key'],KEY);self.assertTrue(result['resumed'])
            self.assertEqual(result['restored_cursor'],3)
            self.assertEqual(result['restored_worker_ids'],['order-details','payment-status','delivery-status'])
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
            document=load_run_state(state_dir,binding_for('crash-submit-window-resolved'))['document']
            self.assertEqual(document['status'],'SUCCEEDED');self.assertIsNotNone(document['effect'])
            resume=events(str(Path(tmp)/'resume.jsonl'))
            self.assertEqual(resume[-1]['type'],'run.completed')
    async def test_resume_unknown_stays_unknown_with_sink_unavailable(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state')
            def on_crash():raise CrashSignal('crash')
            with self.assertRaises(CrashSignal):
                await run_case(case_id='sink-unavailable-unknown',trace_path=str(Path(tmp)/'crash.jsonl'),state_dir=state_dir,on_crash=on_crash)
            result=await run_case(case_id='sink-unavailable-unknown',trace_path=str(Path(tmp)/'resume.jsonl'),state_dir=state_dir,resume=True)
            self.assertEqual(result['status'],'UNKNOWN');self.assertFalse(result['reconciled'])
            self.assertEqual(result['approval_decision'],'granted');self.assertEqual(result['effect_status'],'EFFECT_UNPROVABLE')
            self.assertEqual(result['idempotency_key'],KEY);self.assertIsNone(result['failure_code'])
            self.assertEqual(result['run_state_status'],'UNKNOWN');self.assertTrue(result['resumed'])
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
            document=load_run_state(state_dir,binding_for('sink-unavailable-unknown'))['document']
            self.assertEqual(document['status'],'UNKNOWN');self.assertIsNone(document['effect'])
            resume=events(str(Path(tmp)/'resume.jsonl'))
            self.assertEqual(resume[-1]['type'],'run.completed')
    async def test_resume_before_submit_reruns_the_effect_pipeline(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state')
            def on_crash():raise CrashSignal('crash')
            with self.assertRaises(CrashSignal):
                await run_case(case_id='retry-before-submit',trace_path=str(Path(tmp)/'crash.jsonl'),state_dir=state_dir,on_crash=on_crash)
            crashed=load_run_state(state_dir,binding_for('retry-before-submit'))['document']
            self.assertIsNone(crashed['submit_marker']);self.assertIsNone(crashed['effect'])
            result=await run_case(case_id='retry-before-submit',trace_path=str(Path(tmp)/'resume.jsonl'),state_dir=state_dir,resume=True)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertFalse(result['reconciled'])
            self.assertEqual(result['effect_status'],'EFFECT_COMPLETED');self.assertEqual(result['idempotency_key'],KEY)
            self.assertTrue(result['resumed']);self.assertEqual(result['restored_cursor'],3)
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
            resume=events(str(Path(tmp)/'resume.jsonl'))
            self.assertTrue(any(e['type']=='approval.granted' for e in resume))
            self.assertTrue(any(e['type']=='tool.completed' for e in resume))
            self.assertEqual(resume[-1]['type'],'run.completed')




