import asyncio
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from boundrelay_m5.executor import CrashSignal,execute_workers
from boundrelay_m5.recovery import RecoveryOptions,resume_run
from boundrelay_m5.state_store import StateStore
from boundrelay_m5.effect_ledger import EffectLedger
from boundrelay_m5.audit import AuditWriter
from boundrelay_m5.approval import ApprovalGate
from boundrelay_m5.idempotency import effect_digest,effect_key
from boundrelay_m5.scripted_workers import ScriptedWorkers
from boundrelay_m5.workers import create_worker_directory
from boundrelay_m5.types import (WORKER_IDS,CaseSpec,EffectWiring,ExecutorOptions,
    StateBinding,WorkerInput)

PAYLOAD={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
KEY=effect_key(PAYLOAD);DIGEST=effect_digest(PAYLOAD)
BINDING=StateBinding(case_id='seed',execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

class SpyLedger:
    def __init__(self,real):self._real=real;self.submits=0
    def submit(self,key,digest,payload):
        self.submits+=1;return self._real.submit(key,digest,payload)
    def lookup(self,key):return self._real.lookup(key)
    def records(self):return self._real.records()

class NaiveExampleTests(unittest.TestCase):
    def test_naive_retry_refires_the_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=StateStore(root,BINDING,WORKER_IDS)
            spec=CaseSpec(case_id='seed',execution_mode='parallel',worker_fixture='fixtures/workers/order-brief/complete.yaml',completion_order=WORKER_IDS,approval={'decision':'granted','approver':'approver-primary'})
            provider=ScriptedWorkers(spec,'ORD-1001')
            def on_crash():raise CrashSignal('crash')
            wiring=EffectWiring(ledger=EffectLedger(root),approval_gate=ApprovalGate({'decision':'granted','approver':'approver-primary'}),audit=AuditWriter(root),controls={'crash_in_submit_window':True},on_crash=on_crash)
            async def run():
                return await execute_workers(ExecutorOptions(mode='parallel',input=WorkerInput('ORD-1001'),directory=create_worker_directory(provider),control=provider,observer=lambda event:None,store=store,effect=wiring,completion_order=WORKER_IDS))
            try:asyncio.run(run())
            except CrashSignal:pass
            real=EffectLedger(root)
            self.assertEqual(len(real.records()),1)
            naive=SpyLedger(real)
            refire=naive.submit(KEY,DIGEST,deepcopy(PAYLOAD))
            self.assertTrue(refire['duplicate'])
            self.assertEqual(naive.submits,1)
            self.assertEqual(len(real.records()),1)
            resumed_spy=SpyLedger(real)
            resumed=resume_run(RecoveryOptions(state_root=root,binding=BINDING,ledger=resumed_spy,audit=AuditWriter(root)))
            self.assertEqual(resumed.status,'SUCCEEDED')
            self.assertTrue(resumed.reconciled)
            self.assertEqual(resumed_spy.submits,0)
            self.assertEqual(len(real.records()),1)
