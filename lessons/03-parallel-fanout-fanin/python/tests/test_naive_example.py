import asyncio
import unittest
from boundrelay_m3.executor import execute_workers
from boundrelay_m3.scenario import load_scenario
from boundrelay_m3.scripted_workers import ScriptedWorkers
from boundrelay_m3.workers import create_worker_directory
from boundrelay_m3.types import ExecutorOptions,WorkerInput
from boundrelay_m3.collector import canonicalize_outcomes
from boundrelay_m3.synthesizer import synthesize_brief
async def naive_reads():
    ids=['order-details','payment-status','delivery-status'];sections=[];active=set();peak=0
    entered={i:asyncio.Event() for i in ids};gates={i:asyncio.Event() for i in ids}
    async def read(i):
        nonlocal peak
        active.add(i);peak=max(peak,len(active));entered[i].set();await gates[i].wait();sections.append(i);active.remove(i)
    jobs={i:asyncio.create_task(read(i)) for i in ids}
    for i in ids:await asyncio.wait_for(entered[i].wait(),2)
    for i in ['payment-status','delivery-status','order-details']:gates[i].set();await jobs[i]
    return {'peak':peak,'sections':sections}
class NaiveExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_naive_unbounded_reads_change_report_order(self):
        naive=await naive_reads();self.assertEqual(naive['peak'],3)
        self.assertEqual(naive['sections'],['payment-status','delivery-status','order-details'])
        s=load_scenario();p=ScriptedWorkers(s.cases[2],s.order_id)
        corrected=await execute_workers(ExecutorOptions('parallel',WorkerInput(s.order_id),create_worker_directory(p),p,lambda e:None))
        self.assertEqual(corrected.peak_concurrency,2)
        brief=synthesize_brief(s.order_id,canonicalize_outcomes(corrected.outcomes,s.order_id))
        self.assertEqual([s['worker_id'] for s in brief['sections']],['order-details','payment-status','delivery-status'])
