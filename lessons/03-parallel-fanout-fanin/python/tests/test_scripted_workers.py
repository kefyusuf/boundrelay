import asyncio
import unittest
from boundrelay_m3.scenario import load_scenario
from boundrelay_m3.scripted_workers import ScriptedWorkers
from boundrelay_m3.types import WorkerInput
class ScriptedWorkersTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_requires_entry_and_recorded_ack(self):
        s=load_scenario();p=ScriptedWorkers(s.cases[1],s.order_id);input=WorkerInput('ORD-1001')
        a=asyncio.create_task(p.read('order-details',input))
        b=asyncio.create_task(p.read('payment-status',input))
        await asyncio.wait_for(a,2);self.assertFalse(b.done())
        p.acknowledge_outcome('order-details');await asyncio.wait_for(b,2)
        with self.assertRaises(ValueError):p.acknowledge_outcome('order-details')
        drain=ScriptedWorkers(s.cases[1],s.order_id)
        x=asyncio.create_task(drain.read('order-details',input));y=asyncio.create_task(drain.read('payment-status',input))
        await asyncio.wait_for(x,2);drain.begin_drain();await asyncio.wait_for(y,2)
        with self.assertRaises(ValueError):await drain.read('delivery-status',input)
