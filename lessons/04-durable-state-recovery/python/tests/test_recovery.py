import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from boundrelay_m4.recovery import RunOptions,derive_pending,resume_run,replay_from
from boundrelay_m4.state_store import StateStore,load_run_state
from boundrelay_m4.collector import canonicalize_outcomes
from boundrelay_m4.synthesizer import synthesize_brief
from boundrelay_m4.types import WORKER_IDS,StateBinding,StateLoadError,WorkerDefinition,WorkerOutcome

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

OUTPUTS=({'order_id':'ORD-1001','order_status':'SHIPPED'},{'order_id':'ORD-1001','payment_status':'PAID'},{'order_id':'ORD-1001','delivery_status':'DELIVERED'})

def succeeded(index):
    return {'worker_id':WORKER_IDS[index],'status':'SUCCEEDED','output':dict(OUTPUTS[index]),'failure_code':None}

def failed(index):
    return {'worker_id':WORKER_IDS[index],'status':'FAILED','output':None,'failure_code':'WORKER_EXECUTION_FAILED'}

class Harness:
    def __init__(self):
        self.entered={i:asyncio.Event() for i in WORKER_IDS};self.gates={i:asyncio.Event() for i in WORKER_IDS}
        self.active=set();self.counts={i:0 for i in WORKER_IDS};self.log=[];self.peak=0
    def resolve(self,worker_id):
        async def handle(input):
            self.counts[worker_id]+=1;self.log.append(f'enter:{worker_id}')
            self.active.add(worker_id);self.peak=max(self.peak,len(self.active));self.entered[worker_id].set()
            await self.gates[worker_id].wait();self.active.remove(worker_id)
            return dict(OUTPUTS[WORKER_IDS.index(worker_id)])
        return WorkerDefinition(worker_id,handle)
    def acknowledge_outcome(self,worker_id):pass
    def begin_drain(self):
        for i in self.active:self.gates[i].set()
    async def entered_worker(self,i):await asyncio.wait_for(self.entered[i].wait(),2)

class StubSink:
    def __init__(self,log=None):self.events=[];self.log=log
    def emit(self,type,data):
        self.events.append({'type':type,'data':data})
        if type=='checkpoint.restored' and self.log is not None:self.log.append('restored')
    def restored(self):return [e for e in self.events if e['type']=='checkpoint.restored']

def options(**overrides):
    base={'case_id':'parallel-crash-resume','trace_path':'trace.jsonl','state_dir':tempfile.mkdtemp(prefix='br-m4-rec-')}
    base.update(overrides);return RunOptions(**base)

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._roots=[]
    def root(self):
        path=Path(tempfile.mkdtemp(prefix='br-m4-rec-'));self._roots.append(path);self.addCleanup(shutil.rmtree,path,True);return path
    def store(self,root,case_id):
        return StateStore(root,binding(case_id),WORKER_IDS)
    async def test_resume_skips_recorded_workers_and_reexecutes_inflight_exactly_once(self):
        root=self.root();seed=self.store(root,'parallel-crash-resume')
        seed.mark_running('order-details');seed.record_step_terminal('order-details',succeeded(0));seed.mark_running('payment-status')
        h=Harness();sink=StubSink(h.log);calls={'synth':0}
        def synthesizer(order_id,outcomes):
            calls['synth']+=1;return synthesize_brief(order_id,outcomes)
        run=asyncio.create_task(resume_run(options(state_dir=str(root),sink=sink,directory=h,control=h,synthesizer=synthesizer)))
        await h.entered_worker('payment-status');await h.entered_worker('delivery-status')
        h.gates['payment-status'].set();h.gates['delivery-status'].set()
        result=await asyncio.wait_for(run,2)
        self.assertEqual([h.counts['order-details'],h.counts['payment-status'],h.counts['delivery-status']],[0,1,1])
        self.assertEqual(calls['synth'],1);self.assertTrue(result['synthesis_invoked'])
        self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(result['run_state_status'],'SUCCEEDED')
        self.assertTrue(result['resumed']);self.assertEqual(result['restored_cursor'],1)
        self.assertEqual(result['restored_worker_ids'],['order-details'])
        self.assertEqual(result['peak_concurrency'],2);self.assertEqual(result['state_dir'],str(root))
        self.assertIsNone(result['failure_code']);self.assertTrue(result['brief']['complete']);self.assertEqual(len(result['brief']['sections']),3)
        self.assertEqual(len(sink.restored()),1);self.assertEqual(sink.restored()[0]['data']['state_status'],'RUNNING')
        self.assertEqual(h.log[0],'restored')
        self.assertEqual(load_run_state(root,binding('parallel-crash-resume'))['document']['status'],'SUCCEEDED')
    async def test_resume_never_reexecutes_recorded_failures(self):
        root=self.root();seed=self.store(root,'parallel-crash-resume')
        for index in range(3):seed.record_step_terminal(WORKER_IDS[index],failed(2) if index==2 else succeeded(index))
        h=Harness();sink=StubSink(h.log);captured=[]
        def synthesizer(order_id,outcomes):
            captured.append(outcomes);return synthesize_brief(order_id,outcomes)
        result=await asyncio.wait_for(resume_run(options(state_dir=str(root),sink=sink,directory=h,control=h,synthesizer=synthesizer)),2)
        self.assertEqual(list(h.counts.values()),[0,0,0]);self.assertEqual(h.log,['restored'])
        self.assertEqual(derive_pending(load_run_state(root,binding('parallel-crash-resume'))['document']),[])
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['run_state_status'],'PARTIAL')
        self.assertEqual(result['restored_cursor'],3);self.assertEqual(result['restored_worker_ids'],list(WORKER_IDS))
        self.assertEqual(len(captured),1);self.assertTrue(result['synthesis_invoked'])
        self.assertEqual(next(o for o in captured[0] if o['worker_id']=='delivery-status'),failed(2))
        self.assertFalse(result['brief']['complete']);self.assertEqual(result['brief']['missing_workers'],['delivery-status'])
        self.assertEqual(load_run_state(root,binding('parallel-crash-resume'))['document']['status'],'PARTIAL')

    async def test_replay_seeds_new_run_without_touching_source(self):
        root=self.root();source=self.store(root,'parallel-replay-from-checkpoint')
        source.record_step_terminal('order-details',succeeded(0))
        source_state=source.state_path();snapshot=source.snapshot_path(1)
        before_state=source_state.read_text(encoding='utf-8');before_snapshot=snapshot.read_text(encoding='utf-8')
        h=Harness();sink=StubSink();calls={'synth':0}
        def synthesizer(order_id,outcomes):
            calls['synth']+=1;return synthesize_brief(order_id,outcomes)
        run=asyncio.create_task(replay_from(snapshot,options(case_id='parallel-replay-from-checkpoint',state_dir=str(root),sink=sink,directory=h,control=h,synthesizer=synthesizer)))
        await h.entered_worker('payment-status');await h.entered_worker('delivery-status')
        h.gates['payment-status'].set();h.gates['delivery-status'].set()
        result=await asyncio.wait_for(run,2)
        self.assertNotEqual(result['run_id'],source.state()['run_id'])
        self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(result['restored_cursor'],1)
        self.assertEqual(result['restored_worker_ids'],['order-details'])
        self.assertEqual([h.counts['order-details'],h.counts['payment-status'],h.counts['delivery-status']],[0,1,1])
        self.assertEqual(calls['synth'],1)
        expected=synthesize_brief('ORD-1001',canonicalize_outcomes([succeeded(0),succeeded(1),succeeded(2)],'ORD-1001'))
        self.assertEqual(result['brief'],expected)
        self.assertEqual(source_state.read_text(encoding='utf-8'),before_state)
        self.assertEqual(snapshot.read_text(encoding='utf-8'),before_snapshot)
        self.assertIn(result['run_id'],(root/result['run_id']/'state.json').read_text(encoding='utf-8'))
    async def test_cancel_resume_completes_remaining_workers_only(self):
        root=self.root();seed=self.store(root,'parallel-cancel-resume')
        seed.record_step_terminal('order-details',succeeded(0));seed.record_step_terminal('payment-status',succeeded(1))
        seed.mark_cancelled_from('delivery-status');seed.mark_terminal('CANCELLED')
        h=Harness();sink=StubSink()
        run=asyncio.create_task(resume_run(options(case_id='parallel-cancel-resume',state_dir=str(root),sink=sink,directory=h,control=h,synthesizer=synthesize_brief)))
        await h.entered_worker('delivery-status');h.gates['delivery-status'].set()
        result=await asyncio.wait_for(run,2)
        self.assertEqual(h.counts['delivery-status'],1);self.assertEqual(h.counts['order-details'],0);self.assertEqual(h.counts['payment-status'],0)
        self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(result['run_state_status'],'SUCCEEDED')
        self.assertEqual(result['restored_cursor'],2);self.assertEqual(result['restored_worker_ids'],['order-details','payment-status'])
        self.assertTrue(result['brief']['complete']);self.assertEqual(sink.restored()[0]['data']['state_status'],'CANCELLED')
        document=load_run_state(root,binding('parallel-cancel-resume'))['document']
        self.assertEqual(document['status'],'SUCCEEDED')
        self.assertEqual([step['status'] for step in document['steps']],['SUCCEEDED','SUCCEEDED','SUCCEEDED'])
    async def test_resume_rejects_binding_mismatch_and_terminal_states_without_invocations(self):
        root=self.root();seed=self.store(root,'parallel-crash-resume')
        seed.record_step_terminal('order-details',succeeded(0))
        h=Harness();sink=StubSink()
        with self.assertRaisesRegex(StateLoadError,'BINDING_MISMATCH'):
            await resume_run(options(case_id='parallel-cancel-resume',state_dir=str(root),sink=sink,directory=h,control=h))
        self.assertEqual(list(h.counts.values()),[0,0,0])
        done_root=self.root();done=self.store(done_root,'parallel-crash-resume')
        for index in range(3):done.record_step_terminal(WORKER_IDS[index],succeeded(index))
        done.mark_terminal('SUCCEEDED')
        h2=Harness()
        with self.assertRaisesRegex(ValueError,'not resumable'):
            await resume_run(options(state_dir=str(done_root),sink=sink,directory=h2,control=h2))
        self.assertEqual(list(h2.counts.values()),[0,0,0])


