import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from boundrelay_m4.runner import run_case
from boundrelay_m4.executor import CrashSignal
from boundrelay_m4.state_store import load_run_state
from boundrelay_m4.scenario import load_scenario
from boundrelay_m4.scripted_workers import ScriptedWorkers
from boundrelay_m4.workers import create_worker_directory
from boundrelay_m4.types import StateBinding,WorkerDefinition
from boundrelay_m4.synthesizer import synthesize_brief

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self,case_id):
        s=load_scenario();spec=next(c for c in s.cases if c.case_id==case_id);p=ScriptedWorkers(spec,s.order_id)
        return p,create_worker_directory(p)
    def wrap_gate(self,d,worker_id,entered=None,gate=None,mutate=None):
        original=d.resolve
        def resolve(i):
            w=original(i)
            async def handle(input):
                value=await w.handle(input)
                if i==worker_id:
                    if entered is not None:entered.set()
                    if gate is not None:await gate.wait()
                    if mutate is not None:value=mutate(value)
                return value
            return WorkerDefinition(i,handle)
        d.resolve=resolve
    async def test_synthesis_waits_for_all_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d=self.fixture('parallel-clean-complete');entered=asyncio.Event();gate=asyncio.Event();calls=[]
            self.wrap_gate(d,'delivery-status',entered=entered,gate=gate)
            def synthesize(order_id,outcomes):calls.append(outcomes);return synthesize_brief(order_id,outcomes)
            run=asyncio.create_task(run_case(case_id='parallel-clean-complete',trace_path=str(Path(tmp)/'held.jsonl'),state_dir=str(Path(tmp)/'state'),directory=d,control=p,synthesizer=synthesize))
            await asyncio.wait_for(entered.wait(),2);self.assertEqual(calls,[]);gate.set();result=await asyncio.wait_for(run,2)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(len(calls),1)
            self.assertEqual([o['worker_id'] for o in calls[0]],['order-details','payment-status','delivery-status'])
    async def test_trace_rejects_raw_private_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d=self.fixture('parallel-clean-complete')
            self.wrap_gate(d,'payment-status',mutate=lambda value:{**value,'private':'PRIVATE-PAYLOAD'})
            path=Path(tmp)/'private.jsonl'
            r=await run_case(case_id='parallel-clean-complete',trace_path=str(path),state_dir=str(Path(tmp)/'state'),directory=d,control=p)
            self.assertEqual(r['status'],'PARTIAL');self.assertEqual(r['worker_outcomes'][1]['failure_code'],'INVALID_WORKER_OUTPUT')
            self.assertEqual(r['brief']['missing_workers'],['payment-status']);self.assertNotIn('PRIVATE-PAYLOAD',path.read_text())

    async def test_fatal_run_flushes_prefix_without_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d=self.fixture('parallel-clean-complete')
            self.wrap_gate(d,'order-details',mutate=lambda value:(_ for _ in ()).throw(RuntimeError('unexpected')))
            path=Path(tmp)/'fatal.jsonl'
            with self.assertRaises(RuntimeError):await run_case(case_id='parallel-clean-complete',trace_path=str(path),state_dir=str(Path(tmp)/'state'),directory=d,control=p)
            events=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(events[0]['type'],'run.created')
            self.assertFalse(any(e['type'] in ('run.completed','run.failed','run.cancelled') for e in events))
            self.assertFalse(any(e['data'].get('worker_id')=='delivery-status' for e in events))
    async def test_cancelled_run_is_domain_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cancel.jsonl';state_dir=str(Path(tmp)/'state')
            r=await run_case(case_id='parallel-cancel-resume',trace_path=str(path),state_dir=state_dir)
            self.assertEqual(r['status'],'CANCELLED');self.assertIsNone(r['failure_code'])
            self.assertFalse(r['synthesis_invoked']);self.assertIsNone(r['brief'])
            self.assertEqual(r['run_state_status'],'CANCELLED');self.assertFalse(r['resumed'])
            self.assertIsNone(r['restored_cursor']);self.assertEqual(r['restored_worker_ids'],[])
            events=[json.loads(line) for line in path.read_text().splitlines()]
            cancelled=next(e for e in events if e['type']=='run.cancelled')
            self.assertEqual(cancelled['data']['cancelled_before'],'delivery-status')
            self.assertEqual(cancelled['data']['code'],'CANCELLED_BEFORE_STEP')
            self.assertFalse(any(e['type'] in ('run.completed','run.failed') for e in events))
            document=load_run_state(state_dir,binding('parallel-cancel-resume'))['document']
            self.assertEqual(document['status'],'CANCELLED')
            self.assertEqual([step['status'] for step in document['steps']],['SUCCEEDED','SUCCEEDED','CANCELLED'])
    async def test_crash_phase_flushes_prefix_without_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'crash.jsonl';state_dir=str(Path(tmp)/'state');crashes=[]
            def crash():
                crashes.append(True);raise CrashSignal('crash')
            run=asyncio.create_task(run_case(case_id='parallel-crash-resume',trace_path=str(path),state_dir=state_dir,on_crash=crash))
            with self.assertRaises(CrashSignal):await asyncio.wait_for(run,2)
            self.assertEqual(len(crashes),1)
            events=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(events[0]['type'],'run.created');self.assertEqual(events[-1]['type'],'checkpoint.saved')
            self.assertFalse(any(e['type'] in ('run.completed','run.failed','run.cancelled') for e in events))
            self.assertFalse(any(e['data'].get('step_name')=='worker.delivery-status' for e in events))
            document=load_run_state(state_dir,binding('parallel-crash-resume'))['document']
            self.assertEqual(document['status'],'RUNNING')
            self.assertEqual([step['status'] for step in document['steps']],['SUCCEEDED','SUCCEEDED','PENDING'])
            self.assertEqual(document['sequence_cursor'],2)


