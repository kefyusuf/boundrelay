import asyncio
import tempfile
import unittest
from copy import deepcopy
from boundrelay_m4.executor import execute_workers
from boundrelay_m4.recovery import RunOptions,resume_run
from boundrelay_m4.scenario import load_scenario
from boundrelay_m4.state_store import StateStore
from boundrelay_m4.types import WORKER_IDS,ExecutorOptions,StateBinding,WorkerDefinition,WorkerInput

OUTPUTS={'order-details':{'order_id':'ORD-1001','order_status':'SHIPPED'},
         'payment-status':{'order_id':'ORD-1001','payment_status':'PAID'},
         'delivery-status':{'order_id':'ORD-1001','delivery_status':'DELAYED'}}

class StubSink:
    def emit(self,type,data):pass

class NaiveExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_without_state_duplicates_every_invocation(self):
        scenario=load_scenario();spec=next(c for c in scenario.cases if c.case_id=='parallel-clean-complete')
        binding=StateBinding(case_id=spec.case_id,execution_mode='parallel',requested_order_id=scenario.order_id,concurrency_limit=2)
        with tempfile.TemporaryDirectory() as tmp:
            store=StateStore.create(tmp,binding,list(WORKER_IDS))
            store.record_step_terminal('order-details',{'worker_id':'order-details','status':'SUCCEEDED','output':deepcopy(OUTPUTS['order-details']),'failure_code':None})
            counts={worker_id:0 for worker_id in WORKER_IDS}
            class Counting:
                def resolve(self,worker_id):
                    async def handle(input):
                        counts[worker_id]+=1
                        return deepcopy(OUTPUTS[worker_id])
                    return WorkerDefinition(worker_id,handle)
                def acknowledge_outcome(self,worker_id):pass
                def begin_drain(self):pass
            counting=Counting();directory=type('D',(),{'resolve':counting.resolve})()
            naive=await execute_workers(ExecutorOptions(mode='parallel',input=WorkerInput(scenario.order_id),directory=directory,control=counting,observer=lambda event:None))
            naive_counts=[counts[worker_id] for worker_id in WORKER_IDS]
            self.assertEqual(naive_counts,[1,1,1])
            naive_total=sum(naive_counts)+1
            resumed=await resume_run(RunOptions(case_id='parallel-clean-complete',trace_path='naive.jsonl',state_dir=tmp,sink=StubSink(),directory=directory,control=counting))
            resume_counts=[counts[worker_id] for worker_id in WORKER_IDS]
            self.assertEqual(resume_counts,[1,2,2])
            self.assertEqual(resumed['status'],'SUCCEEDED')
            self.assertEqual(resumed['resumed'],True)
            self.assertEqual(resumed['restored_worker_ids'],['order-details'])
            self.assertEqual((sum(naive_counts)+1,sum(resume_counts)-sum(naive_counts)+1),(4,3))
            self.assertEqual(sum(counts.values())-sum(naive_counts),2)
            self.assertEqual(sum(1 for outcome in naive.outcomes if outcome['status']=='SUCCEEDED'),3)
