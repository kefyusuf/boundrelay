import asyncio
from dataclasses import asdict,FrozenInstanceError
import shutil
import tempfile
import unittest
from boundrelay_m4.executor import CrashSignal,execute_workers
from boundrelay_m4.state_store import StateStore,load_run_state
from boundrelay_m4.scenario import load_scenario
from boundrelay_m4.scripted_workers import ScriptedWorkers
from boundrelay_m4.types import WORKER_IDS,CaseSpec,RecoveryControls,StateBinding,WorkerDefinition,WorkerInput,ExecutorOptions
from boundrelay_m4.workers import create_worker_directory

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

class Harness:
    def __init__(self):
        self.entered={i:asyncio.Event() for i in WORKER_IDS};self.gates={i:asyncio.Event() for i in WORKER_IDS}
        self.active=set();self.counts={i:0 for i in WORKER_IDS};self.inputs=[];self.events=[];self.peak=0;self.drains=0
    def resolve(self,worker_id):
        async def handle(input):
            self.counts[worker_id]+=1;self.inputs.append(input)
            try:input.order_id='ORD-9999'
            except FrozenInstanceError:pass
            else:raise AssertionError('Worker input is mutable')
            self.active.add(worker_id);self.peak=max(self.peak,len(self.active));self.entered[worker_id].set()
            await self.gates[worker_id].wait();self.active.remove(worker_id)
            return [{'order_id':'ORD-1001','order_status':'SHIPPED'},{'order_id':'ORD-1001','payment_status':'PAID'},{'order_id':'ORD-1001','delivery_status':'DELAYED'}][WORKER_IDS.index(worker_id)]
        return WorkerDefinition(worker_id,handle)
    def acknowledge_outcome(self,worker_id):pass
    def begin_drain(self):
        self.drains+=1
        for i in self.active:self.gates[i].set()
    async def entered_worker(self,i):await asyncio.wait_for(self.entered[i].wait(),2)

def wrap_provider(provider):
    counts={i:0 for i in WORKER_IDS};drains=[0];original=provider.read;original_drain=provider.begin_drain
    async def read(worker_id,input):counts[worker_id]+=1;return await original(worker_id,input)
    def begin_drain():drains[0]+=1;original_drain()
    provider.read=read;provider.begin_drain=begin_drain
    return counts,drains

class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp=tempfile.mkdtemp(prefix='br-m4-exec-');self.addCleanup(shutil.rmtree,self._tmp,True)
    def store(self,case_id):
        return StateStore(self._tmp,binding(case_id),WORKER_IDS)
    async def test_parallel_calls_overlap_without_exceeding_two(self):
        h=Harness();store=self.store('probe-parallel');input=WorkerInput('ORD-1001')
        run=asyncio.create_task(execute_workers(ExecutorOptions('parallel',input,h,h,h.events.append,store=store)))
        await h.entered_worker('order-details');await h.entered_worker('payment-status')
        self.assertEqual(h.active,{'order-details','payment-status'});self.assertEqual(h.counts['delivery-status'],0)
        self.assertEqual([s['status'] for s in store.state()['steps']],['RUNNING','RUNNING','PENDING'])
        h.gates['payment-status'].set();await h.entered_worker('delivery-status')
        self.assertIn('order-details',h.active)
        self.assertEqual([e['outcome']['worker_id'] for e in h.events if e['kind']=='terminal'],['payment-status'])
        self.assertEqual(store.state()['sequence_cursor'],1)
        h.gates['delivery-status'].set();h.gates['order-details'].set();summary=await asyncio.wait_for(run,2)
        self.assertEqual(summary.peak_concurrency,2);self.assertEqual(h.peak,2);self.assertEqual(list(h.counts.values()),[1,1,1])
        self.assertEqual(len({id(i) for i in h.inputs}),3);self.assertTrue(all(i is not input for i in h.inputs))
        self.assertEqual([asdict(i) for i in h.inputs],[{'order_id':'ORD-1001'}]*3)
        self.assertEqual(store.state()['sequence_cursor'],3)
        self.assertEqual([s['status'] for s in store.state()['steps']],['SUCCEEDED','SUCCEEDED','SUCCEEDED'])
    async def test_sequential_never_overlaps(self):
        h=Harness();store=self.store('probe-sequential')
        run=asyncio.create_task(execute_workers(ExecutorOptions('sequential',WorkerInput('ORD-1001'),h,h,h.events.append,store=store)))
        for i in WORKER_IDS:
            await h.entered_worker(i);self.assertEqual(h.active,{i});h.gates[i].set()
        summary=await asyncio.wait_for(run,2);self.assertEqual(summary.peak_concurrency,1);self.assertEqual(h.peak,1)
        self.assertEqual(store.state()['sequence_cursor'],3)
        self.assertEqual([s['status'] for s in store.state()['steps']],['SUCCEEDED','SUCCEEDED','SUCCEEDED'])
    async def test_declared_failures_do_not_retry(self):
        for name in ('partial-failure','all-failed','invalid-output'):
            spec=CaseSpec(f'probe-{name}','parallel',f'fixtures/workers/order-brief/{name}.yaml',WORKER_IDS)
            p=ScriptedWorkers(spec,'ORD-1001');counts,_=wrap_provider(p)
            store=self.store(spec.case_id)
            summary=await execute_workers(ExecutorOptions('parallel',WorkerInput('ORD-1001'),create_worker_directory(p),p,lambda e:None,store=store))
            self.assertEqual(list(counts.values()),[1,1,1])
            self.assertEqual(sum(o['status']=='FAILED' for o in summary.outcomes),3 if name=='all-failed' else 1)
            if name=='invalid-output':self.assertEqual(next(o for o in summary.outcomes if o['worker_id']=='payment-status')['failure_code'],'INVALID_WORKER_OUTPUT')
            doc=store.state();self.assertEqual(doc['sequence_cursor'],3)
            self.assertTrue(all(s['status'] in ('SUCCEEDED','FAILED') for s in doc['steps']))
            expected={'invalid-output':'INVALID_WORKER_OUTPUT','all-failed':'WORKER_EXECUTION_FAILED','partial-failure':None}[name]
            self.assertEqual(next(s for s in doc['steps'] if s['worker_id']=='payment-status')['failure_code'],expected)

    async def test_unexpected_error_drains_without_admitting_queued_worker(self):
        h=Harness();store=self.store('probe-fatal');fatal=RuntimeError('unexpected');original=h.resolve
        def resolve(i):
            worker=original(i)
            async def handle(input):
                value=await worker.handle(input)
                if i=='order-details':raise fatal
                return value
            return WorkerDefinition(i,handle)
        h.resolve=resolve
        run=asyncio.create_task(execute_workers(ExecutorOptions('parallel',WorkerInput('ORD-1001'),h,h,h.events.append,store=store)))
        await h.entered_worker('payment-status');h.gates['order-details'].set()
        with self.assertRaises(RuntimeError) as error:await asyncio.wait_for(run,2)
        self.assertIs(error.exception,fatal);self.assertEqual(h.drains,1);self.assertFalse(h.active)
        self.assertEqual(h.counts['delivery-status'],0)
        self.assertFalse(any(e['kind']=='terminal' and e['outcome']['worker_id']=='order-details' for e in h.events))
        self.assertEqual(store.state()['sequence_cursor'],0)
        self.assertEqual([s['status'] for s in store.state()['steps']],['RUNNING','RUNNING','PENDING'])
    async def test_cancel_before_stops_admission_and_records_drained_terminals(self):
        s=load_scenario();spec=next(c for c in s.cases if c.case_id=='parallel-cancel-resume')
        p=ScriptedWorkers(spec,s.order_id);counts,drains=wrap_provider(p)
        store=self.store('parallel-cancel-resume')
        summary=await asyncio.wait_for(execute_workers(ExecutorOptions('parallel',WorkerInput(s.order_id),create_worker_directory(p),p,lambda e:None,store=store,controls=RecoveryControls(cancel_before='delivery-status'),completion_order=spec.completion_order)),2)
        self.assertEqual(summary.cancelled_before,'delivery-status')
        self.assertEqual([o['worker_id'] for o in summary.outcomes],['order-details','payment-status'])
        self.assertEqual(summary.peak_concurrency,2);self.assertEqual(drains[0],0)
        self.assertEqual(list(counts.values()),[1,1,0])
        doc=store.state()
        self.assertEqual([step['status'] for step in doc['steps']],['SUCCEEDED','SUCCEEDED','PENDING'])
        self.assertEqual(doc['sequence_cursor'],2);self.assertEqual(doc['status'],'RUNNING')
    async def _crash_probe(self,case_id,crash_after,expected_statuses,expected_counts):
        s=load_scenario();spec=next(c for c in s.cases if c.case_id==case_id)
        p=ScriptedWorkers(spec,s.order_id);counts,drains=wrap_provider(p)
        store=self.store(case_id)
        crashes=[];at_crash=[]
        def on_crash():
            crashes.append(True);at_crash.append(store.state());raise CrashSignal('crash')
        with self.assertRaises(CrashSignal):
            await asyncio.wait_for(execute_workers(ExecutorOptions('parallel',WorkerInput(s.order_id),create_worker_directory(p),p,lambda e:None,store=store,controls=RecoveryControls(crash_after=crash_after),completion_order=spec.completion_order,on_crash=on_crash)),2)
        self.assertEqual(len(crashes),1);self.assertEqual(drains[0],0)
        self.assertEqual(list(counts.values()),expected_counts)
        document=at_crash[0]
        cursor=sum(1 for status in expected_statuses if status in ('SUCCEEDED','FAILED'))
        self.assertEqual(document['status'],'RUNNING');self.assertEqual(document['sequence_cursor'],cursor)
        self.assertEqual([step['status'] for step in document['steps']],expected_statuses)
        self.assertEqual(load_run_state(store.root,binding(case_id))['document']['sequence_cursor'],cursor)
        return document

    async def test_crash_after_requires_quiescent_boundary(self):
        document=await self._crash_probe('parallel-crash-resume','payment-status',['SUCCEEDED','SUCCEEDED','PENDING'],[1,1,0])
        self.assertIsNone(document['steps'][2]['failure_code'])
    async def test_crash_after_fires_after_recorded_failure(self):
        document=await self._crash_probe('parallel-crash-resume-partial','delivery-status',['SUCCEEDED','SUCCEEDED','FAILED'],[1,1,1])
        self.assertEqual(document['steps'][2]['failure_code'],'WORKER_EXECUTION_FAILED')


