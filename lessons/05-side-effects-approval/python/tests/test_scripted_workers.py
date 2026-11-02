import asyncio
import unittest
from boundrelay_m5.scenario import load_scenario
from boundrelay_m5.scripted_workers import ScriptedWorkers
from boundrelay_m5.types import CaseSpec,WorkerInput

RAISE_SPEC=CaseSpec(case_id='scripted-raise-test',execution_mode='parallel',worker_fixture='fixtures/workers/order-brief/all-failed.yaml',completion_order=('order-details','payment-status','delivery-status'),approval={'decision':'granted','approver':'approver-primary'})

class ScriptedWorkersTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_requires_entry_and_recorded_ack(self):
        s=load_scenario();p=ScriptedWorkers(s.cases[1],s.order_id);value=WorkerInput('ORD-1001')
        a=asyncio.create_task(p.read('order-details',value))
        b=asyncio.create_task(p.read('payment-status',value))
        await asyncio.wait_for(a,2);self.assertFalse(b.done())
        p.acknowledge_outcome('order-details');await asyncio.wait_for(b,2)
        with self.assertRaises(ValueError):p.acknowledge_outcome('order-details')
        drain=ScriptedWorkers(s.cases[1],s.order_id)
        x=asyncio.create_task(drain.read('order-details',value));y=asyncio.create_task(drain.read('payment-status',value))
        await asyncio.wait_for(x,2);drain.begin_drain();await asyncio.wait_for(y,2)
        with self.assertRaises(ValueError):await drain.read('delivery-status',value)
    async def test_declared_worker_failures_raise_worker_execution_error(self):
        p=ScriptedWorkers(RAISE_SPEC,'ORD-1001');value=WorkerInput('ORD-1001')
        a=asyncio.create_task(p.read('order-details',value))
        b=asyncio.create_task(p.read('payment-status',value))
        with self.assertRaisesRegex(Exception,'Declared worker failure'):await asyncio.wait_for(a,2)
        p.acknowledge_outcome('order-details')
        with self.assertRaisesRegex(Exception,'Declared worker failure'):await asyncio.wait_for(b,2)
