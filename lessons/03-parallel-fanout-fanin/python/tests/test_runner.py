import asyncio,json,tempfile
from pathlib import Path
import unittest
from boundrelay_m3.runner import run_case
from boundrelay_m3.scenario import load_scenario
from boundrelay_m3.scripted_workers import ScriptedWorkers
from boundrelay_m3.workers import create_worker_directory
from boundrelay_m3.types import WorkerDefinition
from boundrelay_m3.synthesizer import synthesize_brief
class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        s=load_scenario();p=ScriptedWorkers(s.cases[1],s.order_id);return p,create_worker_directory(p)
    async def test_synthesis_waits_for_all_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d=self.fixture();original=d.resolve;entered=asyncio.Event();gate=asyncio.Event();calls=[]
            def resolve(i):
                w=original(i)
                async def handle(input):
                    value=await w.handle(input)
                    if i=='delivery-status':entered.set();await gate.wait()
                    return value
                return WorkerDefinition(i,handle)
            d.resolve=resolve
            def synthesize(i,outcomes):calls.append(outcomes);return synthesize_brief(i,outcomes)
            run=asyncio.create_task(run_case(case_id='parallel-complete',trace_path=str(Path(tmp)/'held.jsonl'),directory=d,control=p,synthesizer=synthesize))
            await asyncio.wait_for(entered.wait(),2);self.assertEqual(calls,[]);gate.set();result=await asyncio.wait_for(run,2)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(len(calls),1)
            self.assertEqual([o['worker_id'] for o in calls[0]],['order-details','payment-status','delivery-status'])
            calls.clear();failed=await run_case(case_id='parallel-all-failed',trace_path=str(Path(tmp)/'failed.jsonl'),synthesizer=synthesize)
            self.assertEqual(calls,[]);self.assertIsNone(failed['brief']);self.assertFalse(failed['synthesis_invoked'])
    async def test_trace_rejects_raw_private_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d=self.fixture();original=d.resolve
            def resolve(i):
                w=original(i)
                async def handle(input):
                    value=await w.handle(input)
                    return {**value,'private':'PRIVATE-PAYLOAD'} if i=='payment-status' else value
                return WorkerDefinition(i,handle)
            d.resolve=resolve;path=Path(tmp)/'private.jsonl'
            r=await run_case(case_id='parallel-complete',trace_path=str(path),directory=d,control=p)
            self.assertEqual(r['status'],'PARTIAL');self.assertEqual(r['worker_outcomes'][1]['failure_code'],'INVALID_WORKER_OUTPUT')
            self.assertEqual(r['brief']['missing_workers'],['payment-status']);self.assertNotIn('PRIVATE-PAYLOAD',path.read_text())
    async def test_fatal_run_flushes_prefix_without_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d=self.fixture();original=d.resolve
            def resolve(i):
                w=original(i)
                async def handle(input):
                    value=await w.handle(input)
                    if i=='order-details':raise RuntimeError('unexpected')
                    return value
                return WorkerDefinition(i,handle)
            d.resolve=resolve;path=Path(tmp)/'fatal.jsonl'
            with self.assertRaises(RuntimeError):await run_case(case_id='parallel-complete',trace_path=str(path),directory=d,control=p)
            events=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(events[0]['type'],'run.created')
            self.assertFalse(any(e['type'] in ('run.completed','run.failed') for e in events))
            self.assertFalse(any(e['data'].get('worker_id')=='delivery-status' for e in events))
