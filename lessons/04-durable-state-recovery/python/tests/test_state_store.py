import json
import shutil
import tempfile
import unittest
from pathlib import Path
from boundrelay_m4.state_store import StateStore,load_run_state
from boundrelay_m4.types import WORKER_IDS,StateBinding,StateLoadError

BINDING=StateBinding(case_id='parallel-clean-complete',execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)
OUTPUTS=[{'order_id':'ORD-1001','order_status':'SHIPPED'},{'order_id':'ORD-1001','payment_status':'PAID'},{'order_id':'ORD-1001','delivery_status':'DELIVERED'}]

def succeeded(index):
    return {'worker_id':WORKER_IDS[index],'status':'SUCCEEDED','output':dict(OUTPUTS[index]),'failure_code':None}

def failed(index):
    return {'worker_id':WORKER_IDS[index],'status':'FAILED','output':None,'failure_code':'WORKER_EXECUTION_FAILED'}

class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='br-m4-state-'))
        self.addCleanup(self._cleanup)
    def _cleanup(self):
        shutil.rmtree(self.root,ignore_errors=True)
    def store(self):
        return StateStore.create(self.root,BINDING,WORKER_IDS)
    def test_create_writes_initial_loadable_state_and_checkpoints_terminals(self):
        store=self.store();doc=store.state()
        self.assertEqual(doc['status'],'RUNNING');self.assertEqual(doc['sequence_cursor'],0)
        self.assertRegex(doc['digest'],r'^[0-9a-f]{64}$')
        self.assertEqual([s['status'] for s in doc['steps']],['PENDING','PENDING','PENDING'])
        loaded=load_run_state(self.root,BINDING)
        self.assertEqual(loaded['document']['run_id'],doc['run_id']);self.assertEqual(loaded['restored_from'],str(store.state_path()))
        store.mark_running('order-details');self.assertEqual(store.state()['steps'][0]['status'],'RUNNING')
        store.record_step_terminal('order-details',succeeded(0))
        self.assertEqual(store.state()['sequence_cursor'],1)
        snapshot=store.snapshot_path(1).read_text(encoding='utf-8')
        self.assertEqual(json.loads(snapshot)['steps'][0]['output'],dict(OUTPUTS[0]))
        store.record_step_terminal('payment-status',succeeded(1))
        self.assertEqual(store.snapshot_path(1).read_text(encoding='utf-8'),snapshot)
        store.record_step_terminal('delivery-status',failed(2))
        self.assertEqual(store.state()['sequence_cursor'],3);self.assertTrue(store.snapshot_path(3).exists())
    def test_mark_cancelled_from_and_terminal_write_final_state(self):
        store=self.store()
        store.record_step_terminal('order-details',succeeded(0))
        store.record_step_terminal('payment-status',succeeded(1))
        store.mark_cancelled_from('delivery-status')
        self.assertEqual([s['status'] for s in store.state()['steps']],['SUCCEEDED','SUCCEEDED','CANCELLED'])
        store.mark_terminal('CANCELLED')
        self.assertEqual(store.state()['status'],'CANCELLED')
        self.assertEqual(load_run_state(self.root,BINDING)['document']['status'],'CANCELLED')
        with self.assertRaises(ValueError):store.mark_terminal('FAILED','OTHER')
    def test_reject_tampered_state_document(self):
        store=self.store()
        store.record_step_terminal('order-details',succeeded(0))
        store.record_step_terminal('payment-status',succeeded(1))
        path=store.state_path();good=path.read_text(encoding='utf-8')
        def mutate(apply):
            doc=json.loads(good);apply(doc);path.write_text(json.dumps(doc),encoding='utf-8')
        def reason(binding=BINDING):
            try:
                load_run_state(self.root,binding);self.fail('expected StateLoadError')
            except StateLoadError as error:
                return str(error)
            return ''
        mutate(lambda doc:doc['steps'][1]['output'].update(payment_status='UNPAID'))
        message=reason();self.assertIn('DIGEST_MISMATCH',message);self.assertNotIn('UNPAID',message)
        mutate(lambda doc:doc.update(state_schema_version='2.0'))
        self.assertIn('UNKNOWN_VERSION',reason())
        mutate(lambda doc:doc.pop('sequence_cursor'))
        self.assertIn('SCHEMA_INVALID',reason())
        mutate(lambda doc:doc.update(digest='a'*64))
        self.assertIn('DIGEST_MISMATCH',reason())
        path.write_text(good,encoding='utf-8')
        self.assertIn('BINDING_MISMATCH',reason(StateBinding(case_id='other-case',execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)))
        path.write_text('{"state_schema_version":"1.0","run_',encoding='utf-8')
        self.assertIn('TRUNCATED',reason())
        path.write_text(good,encoding='utf-8')
    def test_atomic_write_leaves_previous_state_loadable(self):
        store=self.store();store.record_step_terminal('order-details',succeeded(0))
        path=store.state_path();tmp=Path(str(path)+'.tmp')
        tmp.write_text('{"state_schema_version":"1.0","run_',encoding='utf-8')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['steps'][0]['status'],'SUCCEEDED')
        self.assertEqual(load_run_state(self.root,BINDING)['document']['sequence_cursor'],1)
        store.mark_running('payment-status')
        self.assertFalse(tmp.exists())
        self.assertEqual(load_run_state(self.root,BINDING)['document']['steps'][1]['status'],'RUNNING')
    def test_missing_checkpoint_snapshot_fails_closed(self):
        store=self.store();store.record_step_terminal('order-details',succeeded(0))
        store.snapshot_path(1).unlink()
        with self.assertRaisesRegex(StateLoadError,'MISSING_SNAPSHOT'):load_run_state(self.root,BINDING)
    def test_flat_layout_loads_and_ambiguous_discovery_fails(self):
        store=self.store();store.record_step_terminal('order-details',succeeded(0))
        flat=self.root/'state.json';nested=store.state_path()
        flat.write_text(nested.read_text(encoding='utf-8'),encoding='utf-8')
        loaded=load_run_state(self.root,BINDING)
        self.assertEqual(loaded['restored_from'],str(flat));self.assertEqual(loaded['document']['run_id'],store.state()['run_id'])
        flat.unlink()
        self.assertEqual(load_run_state(self.root,BINDING)['restored_from'],str(nested))
        empty=Path(tempfile.mkdtemp(prefix='br-m4-empty-'));self.addCleanup(lambda:shutil.rmtree(empty,ignore_errors=True))
        with self.assertRaises(ValueError):load_run_state(empty,BINDING)
        StateStore.create(empty,BINDING,WORKER_IDS);StateStore.create(empty,BINDING,WORKER_IDS)
        with self.assertRaises(ValueError):load_run_state(empty,BINDING)



