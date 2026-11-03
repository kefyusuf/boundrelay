import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from boundrelay_m5.executor import CrashSignal,execute_workers
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
KEY=effect_key(PAYLOAD)
DIGEST=effect_digest(PAYLOAD)
CONFIRMED={'key':KEY,'payload_digest':DIGEST,'status':'EFFECT_COMPLETED','outcome':{'refund_id':'RFL-1001','refunded_at':'2026-11-02T00:00:00Z'},'duplicate':False}
EFFECT_EVENT_NAMES=('audit-approval','marker','submit','store-effect','audit-effect','crash')

class WrappedProvider:
    def __init__(self,provider,counts,active,peak,drains):
        self._provider=provider;self._counts=counts;self._active=active;self._peak=peak;self._drains=drains
    async def read(self,worker_id,value):
        self._counts[worker_id]+=1;self._active.add(worker_id)
        self._peak['value']=max(self._peak['value'],len(self._active))
        try:return await self._provider.read(worker_id,value)
        finally:self._active.discard(worker_id)
    def acknowledge_outcome(self,worker_id):self._provider.acknowledge_outcome(worker_id)
    def begin_drain(self):self._drains['value']+=1;self._provider.begin_drain()

class WrappedStore:
    def __init__(self,real,events):
        self._real=real;self._events=events
    def mark_running(self,worker_id):self._events.append(f'start:{worker_id}');self._real.mark_running(worker_id)
    def record_step_terminal(self,worker_id,outcome):self._events.append(f'terminal:{worker_id}');self._real.record_step_terminal(worker_id,outcome)
    def mark_cancelled_from(self,worker_id):self._real.mark_cancelled_from(worker_id)
    def mark_terminal(self,status,failure_code=None):self._real.mark_terminal(status,failure_code)
    def mark_submitted(self,key,digest):self._events.append('marker');self._real.mark_submitted(key,digest)
    def record_effect_outcome(self,effect):self._events.append('store-effect');self._real.record_effect_outcome(effect)
    def state(self):return self._real.state()
    def state_path(self):return self._real.state_path()
    def snapshot_path(self,seq):return self._real.snapshot_path(seq)
class WrappedLedger:
    def __init__(self,real,events):
        self._real=real;self._events=events
    def submit(self,key,digest,payload):
        self._events.append('submit');return self._real.submit(key,digest,payload)
    def lookup(self,key):return self._real.lookup(key)

class WrappedAudit:
    def __init__(self,real,events):
        self._real=real;self._events=events
    def append(self,record):
        self._events.append('audit-approval' if record['kind']=='approval' else 'audit-effect')
        self._real.append(record)

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='br-m5-exec-'))
        self.addCleanup(self._cleanup)
    def _cleanup(self):
        shutil.rmtree(self.root,ignore_errors=True)
    def probe(self,decision,fixture='complete',controls=None):
        events=[]
        spec=CaseSpec(case_id='probe',execution_mode='parallel',worker_fixture=f'fixtures/workers/order-brief/{fixture}.yaml',completion_order=WORKER_IDS,approval={'decision':'granted','approver':'approver-primary'})
        provider=ScriptedWorkers(spec,'ORD-1001')
        counts={worker_id:0 for worker_id in WORKER_IDS}
        active=set();peak={'value':0};drains={'value':0};crashes={'value':0}
        wrapped=WrappedProvider(provider,counts,active,peak,drains)
        directory=create_worker_directory(wrapped)
        real_store=StateStore(self.root,StateBinding(case_id='probe',execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2),WORKER_IDS)
        store=WrappedStore(real_store,events)
        real_ledger=EffectLedger(self.root)
        ledger=WrappedLedger(real_ledger,events)
        real_audit=AuditWriter(self.root)
        audit=WrappedAudit(real_audit,events)
        gate=ApprovalGate({'decision':decision,'approver':'approver-primary'})
        def on_crash():
            crashes['value']+=1;events.append('crash');raise CrashSignal('crash')
        wiring=EffectWiring(ledger=ledger,approval_gate=gate,audit=audit,controls=controls,on_crash=on_crash)
        async def run():
            return await execute_workers(ExecutorOptions(mode='parallel',input=WorkerInput('ORD-1001'),directory=directory,control=wrapped,observer=lambda event:None,store=store,effect=wiring,completion_order=WORKER_IDS))
        def effect_events():
            return [name for name in events if name in EFFECT_EVENT_NAMES]
        return {'run':run,'store':real_store,'ledger':real_ledger,'audit':real_audit,
                'counts':counts,'drains':drains,'peak':peak,'crashes':crashes,
                'effect_events':effect_events}

    def test_no_submission_without_granted_approval(self):
        probe=self.probe('rejected')
        summary=asyncio.run(probe['run']())
        self.assertTrue(summary.rejected);self.assertIsNone(summary.effect)
        self.assertEqual(probe['ledger'].records(),[])
        self.assertEqual(probe['audit'].records(),[{'kind':'approval','operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':DIGEST,'decision':'rejected','approver':'approver-primary'}])
        self.assertEqual(probe['effect_events'](),['audit-approval'])
        self.assertIsNone(probe['store'].state()['submit_marker'])
        self.assertIsNone(probe['store'].state()['effect'])
    def test_submit_marker_precedes_ledger_submit_and_outcome_recorded_after(self):
        probe=self.probe('granted')
        summary=asyncio.run(probe['run']())
        self.assertFalse(summary.rejected);self.assertEqual(summary.effect,CONFIRMED)
        self.assertEqual(probe['effect_events'](),['audit-approval','marker','submit','store-effect','audit-effect'])
        self.assertEqual(probe['store'].state()['effect'],CONFIRMED)
        crashed=self.probe('granted',controls={'crash_in_submit_window':True})
        with self.assertRaises(CrashSignal):asyncio.run(crashed['run']())
        self.assertEqual(crashed['crashes']['value'],1);self.assertEqual(crashed['drains']['value'],0)
        self.assertEqual(crashed['effect_events'](),['audit-approval','marker','submit','crash'])
        self.assertEqual(crashed['store'].state()['submit_marker'],{'key':KEY,'payload_digest':DIGEST})
        self.assertIsNone(crashed['store'].state()['effect'])
        self.assertEqual(len(crashed['ledger'].records()),1)
    def test_reads_bounded_and_effect_submitted_once(self):
        probe=self.probe('granted')
        summary=asyncio.run(probe['run']())
        self.assertEqual(list(probe['counts'].values()),[1,1,1])
        self.assertLessEqual(probe['peak']['value'],2);self.assertEqual(summary.peak_concurrency,2)
        self.assertEqual([r['status'] for r in summary.reads],['SUCCEEDED','SUCCEEDED','SUCCEEDED'])
        self.assertEqual([r['worker_id'] for r in summary.reads],list(WORKER_IDS))
        self.assertEqual(probe['ledger'].records(),[{'key':KEY,'payload_digest':DIGEST,'effect':{'status':'EFFECT_COMPLETED','outcome':CONFIRMED['outcome']}}])
        self.assertEqual([r['kind'] for r in probe['audit'].records()],['approval','effect'])
        self.assertEqual(probe['audit'].records()[1],{'kind':'effect','operation':'cancel-and-refund','order_id':'ORD-1001','idempotency_key':KEY,'effect_status':'EFFECT_COMPLETED','duplicate':False})
    def test_declared_read_failures_stop_before_approval(self):
        for fixture in ('partial-failure','all-failed'):
            probe=self.probe('granted',fixture=fixture)
            summary=asyncio.run(probe['run']())
            self.assertFalse(summary.rejected);self.assertIsNone(summary.effect)
            self.assertTrue(any(r['status']=='FAILED' for r in summary.reads))
            self.assertEqual(probe['ledger'].records(),[]);self.assertEqual(probe['audit'].records(),[])
            self.assertEqual(probe['effect_events'](),[])
    def test_store_is_optional_plain_m4_reads_when_absent(self):
        spec=CaseSpec(case_id='probe-nostore',execution_mode='parallel',worker_fixture='fixtures/workers/order-brief/complete.yaml',completion_order=WORKER_IDS,approval={'decision':'granted','approver':'approver-primary'})
        provider=ScriptedWorkers(spec,'ORD-1001')
        ledger=EffectLedger(self.root)
        wiring=EffectWiring(ledger=ledger,approval_gate=ApprovalGate({'decision':'granted','approver':'approver-primary'}))
        async def run():
            return await execute_workers(ExecutorOptions(mode='parallel',input=WorkerInput('ORD-1001'),directory=create_worker_directory(provider),control=provider,observer=lambda event:None,effect=wiring,completion_order=WORKER_IDS))
        summary=asyncio.run(run())
        self.assertEqual([r['status'] for r in summary.reads],['SUCCEEDED','SUCCEEDED','SUCCEEDED'])
        self.assertIsNone(summary.effect);self.assertFalse(summary.rejected)
        self.assertEqual(ledger.records(),[])
    def test_crash_before_submit_fires_before_the_marker(self):
        probe=self.probe('granted',controls={'crash_before_submit':True})
        with self.assertRaises(CrashSignal):asyncio.run(probe['run']())
        self.assertEqual(probe['crashes']['value'],1);self.assertEqual(probe['drains']['value'],0)
        self.assertEqual(probe['effect_events'](),['audit-approval','crash'])
        self.assertEqual(probe['ledger'].records(),[])
        self.assertIsNone(probe['store'].state()['submit_marker'])





