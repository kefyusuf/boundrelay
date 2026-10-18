import asyncio
from dataclasses import asdict,FrozenInstanceError
import unittest
from boundrelay_m3.executor import execute_workers
from boundrelay_m3.types import WORKER_IDS,WorkerInput,WorkerDefinition,ExecutorOptions
from boundrelay_m3.scenario import load_scenario
from boundrelay_m3.scripted_workers import ScriptedWorkers
from boundrelay_m3.workers import create_worker_directory

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

class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_calls_overlap_without_exceeding_two(self):
        h=Harness();input=WorkerInput('ORD-1001')
        run=asyncio.create_task(execute_workers(ExecutorOptions('parallel',input,h,h,h.events.append)))
        await h.entered_worker('order-details');await h.entered_worker('payment-status')
        self.assertEqual(h.active,{'order-details','payment-status'});self.assertEqual(h.counts['delivery-status'],0)
        h.gates['payment-status'].set();await h.entered_worker('delivery-status')
        self.assertIn('order-details',h.active)
        self.assertEqual([e['outcome']['worker_id'] for e in h.events if e['kind']=='terminal'],['payment-status'])
        h.gates['delivery-status'].set();h.gates['order-details'].set();summary=await asyncio.wait_for(run,2)
        self.assertEqual(summary.peak_concurrency,2);self.assertEqual(h.peak,2);self.assertEqual(list(h.counts.values()),[1,1,1])
        self.assertEqual(len({id(i) for i in h.inputs}),3);self.assertTrue(all(i is not input for i in h.inputs))
        self.assertEqual([asdict(i) for i in h.inputs],[{'order_id':'ORD-1001'}]*3)
    async def test_sequential_never_overlaps(self):
        h=Harness();run=asyncio.create_task(execute_workers(ExecutorOptions('sequential',WorkerInput('ORD-1001'),h,h,h.events.append)))
        for i in WORKER_IDS:
            await h.entered_worker(i);self.assertEqual(h.active,{i});h.gates[i].set()
        summary=await asyncio.wait_for(run,2);self.assertEqual(summary.peak_concurrency,1);self.assertEqual(h.peak,1)
    async def test_declared_failures_do_not_retry(self):
        s=load_scenario()
        for name in ('parallel-partial-failure','parallel-all-failed','parallel-invalid-output'):
            p=ScriptedWorkers(next(c for c in s.cases if c.case_id==name),s.order_id);counts={i:0 for i in WORKER_IDS}
            original=p.read
            async def read(i,input):counts[i]+=1;return await original(i,input)
            p.read=read
            summary=await execute_workers(ExecutorOptions('parallel',WorkerInput(s.order_id),create_worker_directory(p),p,lambda e:None))
            self.assertEqual(list(counts.values()),[1,1,1])
            self.assertEqual(sum(o['status']=='FAILED' for o in summary.outcomes),3 if name=='parallel-all-failed' else 1)
            if name=='parallel-invalid-output':self.assertEqual(next(o for o in summary.outcomes if o['worker_id']=='payment-status')['failure_code'],'INVALID_WORKER_OUTPUT')
    async def test_unexpected_error_drains_without_admitting_queued_worker(self):
        h=Harness();fatal=RuntimeError('unexpected');original=h.resolve
        def resolve(i):
            worker=original(i)
            async def handle(input):
                value=await worker.handle(input)
                if i=='order-details':raise fatal
                return value
            return WorkerDefinition(i,handle)
        h.resolve=resolve
        run=asyncio.create_task(execute_workers(ExecutorOptions('parallel',WorkerInput('ORD-1001'),h,h,h.events.append)))
        await h.entered_worker('payment-status');h.gates['order-details'].set()
        with self.assertRaises(RuntimeError) as error:await asyncio.wait_for(run,2)
        self.assertIs(error.exception,fatal);self.assertEqual(h.drains,1);self.assertFalse(h.active)
        self.assertEqual(h.counts['delivery-status'],0)
        self.assertFalse(any(e['kind']=='terminal' and e['outcome']['worker_id']=='order-details' for e in h.events))
