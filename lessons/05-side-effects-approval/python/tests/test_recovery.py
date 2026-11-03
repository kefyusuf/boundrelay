import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from boundrelay_m5.executor import CrashSignal,execute_workers
from boundrelay_m5.recovery import RecoveryError,RecoveryOptions,resume_run
from boundrelay_m5.state_store import StateStore,load_run_state
from boundrelay_m5.effect_ledger import EffectLedger
from boundrelay_m5.audit import AuditWriter
from boundrelay_m5.approval import ApprovalGate
from boundrelay_m5.idempotency import effect_digest,effect_key
from boundrelay_m5.schemas import canonical_json,canonical_state_body,state_digest
from boundrelay_m5.scripted_workers import ScriptedWorkers
from boundrelay_m5.workers import create_worker_directory
from boundrelay_m5.types import (WORKER_IDS,CaseSpec,EffectWiring,ExecutorOptions,
    StateBinding,WorkerInput)

PAYLOAD={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
KEY=effect_key(PAYLOAD)
DIGEST=effect_digest(PAYLOAD)
OUTCOME={'refund_id':'RFL-1001','refunded_at':'2026-11-02T00:00:00Z'}
ADOPTED={'key':KEY,'payload_digest':DIGEST,'status':'EFFECT_COMPLETED','outcome':OUTCOME,'duplicate':False}
BINDING=StateBinding(case_id='seed',execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

class SpyLedger:
    def __init__(self,real):
        self._real=real;self.submits=0;self.lookups=0
    def submit(self,key,digest,payload):
        self.submits+=1;return self._real.submit(key,digest,payload)
    def lookup(self,key):
        self.lookups+=1;return self._real.lookup(key)

class SpyAudit:
    def __init__(self,real):
        self._real=real;self.reads=0
    def append(self,record):self._real.append(record)
    def records(self):
        self.reads+=1;return self._real.records()
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='br-m5-rec-'))
        self.addCleanup(self._cleanup)
    def _cleanup(self):
        shutil.rmtree(self.root,ignore_errors=True)
    def seed_run(self,decision='granted',controls=None,root=None):
        root=self.root if root is None else root
        spec=CaseSpec(case_id='seed',execution_mode='parallel',worker_fixture='fixtures/workers/order-brief/complete.yaml',completion_order=WORKER_IDS,approval={'decision':'granted','approver':'approver-primary'})
        provider=ScriptedWorkers(spec,'ORD-1001')
        store=StateStore(root,BINDING,WORKER_IDS)
        def on_crash():raise CrashSignal('crash')
        wiring=EffectWiring(ledger=EffectLedger(root),approval_gate=ApprovalGate({'decision':decision,'approver':'approver-primary'}),audit=AuditWriter(root),controls=controls,on_crash=on_crash)
        async def run():
            return await execute_workers(ExecutorOptions(mode='parallel',input=WorkerInput('ORD-1001'),directory=create_worker_directory(provider),control=provider,observer=lambda event:None,store=store,effect=wiring,completion_order=WORKER_IDS))
        try:
            asyncio.run(run())
        except CrashSignal:
            pass
    def spies(self,root=None):
        root=self.root if root is None else root
        real_ledger=EffectLedger(root);real_audit=AuditWriter(root)
        return {'ledger':real_ledger,'audit':real_audit,'ledger_spy':SpyLedger(real_ledger),'audit_spy':SpyAudit(real_audit)}
    def test_resume_proves_landed_effect_by_key_lookup(self):
        self.seed_run(controls={'crash_in_submit_window':True})
        spy=self.spies()
        result=resume_run(RecoveryOptions(state_root=self.root,binding=BINDING,ledger=spy['ledger_spy'],audit=spy['audit_spy']))
        self.assertEqual(result.status,'SUCCEEDED');self.assertTrue(result.reconciled)
        self.assertEqual(result.idempotency_key,KEY);self.assertEqual(result.effect,ADOPTED)
        self.assertEqual([r['status'] for r in result.reads],['SUCCEEDED','SUCCEEDED','SUCCEEDED'])
        document=load_run_state(self.root,BINDING)['document']
        self.assertEqual(document['status'],'SUCCEEDED');self.assertEqual(document['effect'],ADOPTED)
        self.assertEqual(document['submit_marker'],{'key':KEY,'payload_digest':DIGEST})
        self.assertEqual(spy['ledger'].records(),[{'key':KEY,'payload_digest':DIGEST,'effect':{'status':'EFFECT_COMPLETED','outcome':OUTCOME}}])
        self.assertEqual(spy['ledger_spy'].submits,0)
        self.assertEqual([r['kind'] for r in spy['audit'].records()],['approval','effect'])
        self.assertEqual(spy['audit_spy'].reads,0)
    def test_resume_resubmits_absent_effect_under_same_key(self):
        self.seed_run(controls={'crash_in_submit_window':True})
        (self.root/'effect-ledger.json').unlink()
        spy=self.spies()
        result=resume_run(RecoveryOptions(state_root=self.root,binding=BINDING,ledger=spy['ledger_spy'],audit=spy['audit_spy']))
        self.assertEqual(result.status,'SUCCEEDED');self.assertFalse(result.reconciled)
        self.assertEqual(result.effect,dict(ADOPTED,duplicate=False))
        self.assertEqual(spy['ledger'].records(),[{'key':KEY,'payload_digest':DIGEST,'effect':{'status':'EFFECT_COMPLETED','outcome':OUTCOME}}])
        self.assertEqual(spy['ledger_spy'].submits,1);self.assertEqual(spy['ledger_spy'].lookups,1)
        document=load_run_state(self.root,BINDING)['document']
        self.assertEqual(document['status'],'SUCCEEDED');self.assertEqual(document['effect'],result.effect)
        self.assertEqual([r['kind'] for r in spy['audit'].records()],['approval','effect'])
    def test_unprovable_effect_stays_unknown(self):
        self.seed_run(controls={'crash_in_submit_window':True})
        spy=self.spies()
        result=resume_run(RecoveryOptions(state_root=self.root,binding=BINDING,ledger=spy['ledger_spy'],audit=spy['audit_spy'],controls={'sink_unavailable':True}))
        self.assertEqual(result.status,'UNKNOWN');self.assertFalse(result.reconciled)
        self.assertIsNone(result.effect);self.assertEqual(result.idempotency_key,KEY)
        self.assertEqual(spy['ledger_spy'].lookups,0);self.assertEqual(spy['ledger_spy'].submits,0)
        document=load_run_state(self.root,BINDING)['document']
        self.assertEqual(document['status'],'UNKNOWN');self.assertIsNone(document['effect'])
        self.assertEqual(document['submit_marker'],{'key':KEY,'payload_digest':DIGEST})
        self.assertEqual(len(spy['ledger'].records()),1)
        self.assertEqual(len(spy['audit'].records()),1)
        self.assertEqual(spy['audit_spy'].reads,0)
    def test_duplicate_key_adopts_recorded_outcome(self):
        self.seed_run()
        ledger=EffectLedger(self.root)
        self.assertEqual(len(ledger.records()),1)
        spec=CaseSpec(case_id='second',execution_mode='parallel',worker_fixture='fixtures/workers/order-brief/complete.yaml',completion_order=WORKER_IDS,approval={'decision':'granted','approver':'approver-primary'})
        provider=ScriptedWorkers(spec,'ORD-1001')
        store=StateStore(self.root,BINDING,WORKER_IDS)
        wiring=EffectWiring(ledger=ledger,approval_gate=ApprovalGate({'decision':'granted','approver':'approver-primary'}),audit=AuditWriter(self.root))
        async def run():
            return await execute_workers(ExecutorOptions(mode='parallel',input=WorkerInput('ORD-1001'),directory=create_worker_directory(provider),control=provider,observer=lambda event:None,store=store,effect=wiring,completion_order=WORKER_IDS))
        summary=asyncio.run(run())
        self.assertEqual(summary.effect,dict(ADOPTED,duplicate=True))
        self.assertEqual(len(ledger.records()),1)
        self.assertEqual(store.state()['effect'],dict(ADOPTED,duplicate=True))
        self.assertEqual(store.state()['submit_marker'],{'key':KEY,'payload_digest':DIGEST})
    def test_terminal_states_not_resumable(self):
        for status in ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):
            with self.subTest(status=status):
                root=Path(tempfile.mkdtemp(prefix='br-m5-rec-'))
                self.addCleanup(shutil.rmtree,root,ignore_errors=True)
                self.seed_run(root=root)
                loaded=load_run_state(root,BINDING)
                store=StateStore.resume(loaded['document'],loaded['restored_from'])
                if status=='FAILED':store.mark_terminal('FAILED','APPROVAL_REJECTED')
                else:store.mark_terminal(status)
                spy=self.spies(root)
                with self.assertRaisesRegex(RecoveryError,'not resumable'):
                    resume_run(RecoveryOptions(state_root=root,binding=BINDING,ledger=spy['ledger_spy'],audit=spy['audit_spy']))
                self.assertEqual(len(spy['ledger'].records()),1);self.assertEqual(spy['ledger_spy'].submits,0)
                self.assertEqual(len(spy['audit'].records()),2);self.assertEqual(spy['audit_spy'].reads,0)
    def test_binding_mismatch_rejected(self):
        self.seed_run(controls={'crash_in_submit_window':True})
        restored_from=load_run_state(self.root,BINDING)['restored_from']
        doc=json.loads(Path(restored_from).read_text(encoding='utf-8'))
        doc['submit_marker']={'key':KEY,'payload_digest':'d'*64}
        doc['digest']=state_digest(canonical_state_body(doc))
        Path(restored_from).write_text(canonical_json(doc),encoding='utf-8')
        spy=self.spies()
        with self.assertRaisesRegex(RecoveryError,'Effect binding mismatch'):
            resume_run(RecoveryOptions(state_root=self.root,binding=BINDING,ledger=spy['ledger_spy'],audit=spy['audit_spy']))
        self.assertEqual(len(spy['ledger'].records()),1);self.assertEqual(spy['ledger_spy'].submits,0)
        self.assertEqual(spy['ledger_spy'].lookups,0)
        self.assertEqual(len(spy['audit'].records()),1);self.assertEqual(spy['audit_spy'].reads,0)
    def test_runtime_never_reads_audit(self):
        self.seed_run(controls={'crash_in_submit_window':True})
        spy=self.spies()
        resume_run(RecoveryOptions(state_root=self.root,binding=BINDING,ledger=spy['ledger_spy'],audit=spy['audit_spy']))
        self.assertEqual(spy['audit_spy'].reads,0)





