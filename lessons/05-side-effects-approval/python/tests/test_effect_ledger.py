import json
import shutil
import tempfile
import unittest
from pathlib import Path
from boundrelay_m5.effect_ledger import EffectLedger
from boundrelay_m5.idempotency import effect_digest,effect_key

PAYLOAD={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
KEY=effect_key(PAYLOAD)
DIGEST=effect_digest(PAYLOAD)
OUTCOME={'refund_id':'RFL-1001','refunded_at':'2026-11-02T00:00:00Z'}

class EffectLedgerTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='br-m5-ledger-'))
        self.addCleanup(self._cleanup)
    def _cleanup(self):
        shutil.rmtree(self.root,ignore_errors=True)
    def test_ledger_enforces_once_per_key_with_deterministic_outcome(self):
        ledger=EffectLedger(self.root)
        self.assertEqual(ledger.path(),self.root/'effect-ledger.json')
        self.assertIsNone(ledger.lookup(KEY))
        first=ledger.submit(KEY,DIGEST,PAYLOAD)
        self.assertEqual(first,{'status':'EFFECT_COMPLETED','outcome':OUTCOME,'reason':None,'duplicate':False})
        self.assertEqual(ledger.records(),[{'key':KEY,'payload_digest':DIGEST,'effect':{'status':'EFFECT_COMPLETED','outcome':OUTCOME}}])
        before=ledger.path().read_text(encoding='utf-8')
        second=ledger.submit(KEY,DIGEST,PAYLOAD)
        self.assertEqual(second,{'status':'EFFECT_COMPLETED','outcome':OUTCOME,'reason':None,'duplicate':True})
        self.assertEqual(len(ledger.records()),1)
        self.assertEqual(ledger.path().read_text(encoding='utf-8'),before)
        self.assertEqual(ledger.lookup(KEY),{'status':'EFFECT_COMPLETED','outcome':OUTCOME})
    def test_invalid_payload_is_rejected_once_and_adopted_on_duplicate(self):
        bad={**PAYLOAD,'refund_amount_cents':9999}
        ledger=EffectLedger(self.root)
        first=ledger.submit(KEY,effect_digest(bad),bad)
        self.assertEqual(first,{'status':'EFFECT_REJECTED','outcome':None,'reason':'INVALID_PAYLOAD','duplicate':False})
        self.assertEqual(len(ledger.records()),1)
        self.assertEqual(ledger.records()[0]['effect'],{'status':'EFFECT_REJECTED','outcome':None,'reason':'INVALID_PAYLOAD'})
        again=ledger.submit(KEY,effect_digest(bad),bad)
        self.assertEqual(again,{'status':'EFFECT_REJECTED','outcome':None,'reason':'INVALID_PAYLOAD','duplicate':True})
        self.assertEqual(len(ledger.records()),1)
        self.assertEqual(ledger.lookup(KEY),{'status':'EFFECT_REJECTED','outcome':None})
    def test_extra_field_payload_is_rejected(self):
        ledger=EffectLedger(self.root)
        result=ledger.submit(KEY,effect_digest({**PAYLOAD,'memo':'x'}),{**PAYLOAD,'memo':'x'})
        self.assertEqual(result['status'],'EFFECT_REJECTED');self.assertFalse(result['duplicate'])
    def test_atomic_write_leaves_previous_ledger_loadable(self):
        ledger=EffectLedger(self.root)
        ledger.submit(KEY,DIGEST,PAYLOAD)
        tmp=Path(str(ledger.path())+'.tmp');tmp.write_text('{"records": [',encoding='utf-8')
        self.assertEqual(ledger.lookup(KEY)['status'],'EFFECT_COMPLETED')
        reopened=EffectLedger(self.root)
        self.assertEqual(reopened.lookup(KEY),ledger.lookup(KEY))
        other={**PAYLOAD,'order_id':'ORD-1002'}
        reopened.submit(effect_key(other),effect_digest(other),other)
        self.assertFalse(tmp.exists())
    def test_ledger_persists_across_instances_and_keys_stay_distinct(self):
        EffectLedger(self.root).submit(KEY,DIGEST,PAYLOAD)
        ledger=EffectLedger(self.root)
        self.assertEqual(len(ledger.records()),1)
        other={**PAYLOAD,'order_id':'ORD-1002'}
        result=ledger.submit(effect_key(other),effect_digest(other),other)
        self.assertFalse(result['duplicate'])
        self.assertEqual(len(ledger.records()),2)
        self.assertEqual(ledger.lookup(effect_key(other))['status'],'EFFECT_COMPLETED')
        self.assertIsNone(ledger.lookup('cancel-and-refund:ORD-9999'))
    def test_corrupt_ledger_file_fails_closed(self):
        EffectLedger(self.root)
        (self.root/'effect-ledger.json').write_text('{"records": [',encoding='utf-8')
        with self.assertRaises(Exception):EffectLedger(self.root).lookup(KEY)



