import shutil
import tempfile
import unittest
from pathlib import Path
from boundrelay_m5.audit import AuditWriter

DIGEST='c'*64
APPROVAL={'kind':'approval','operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':DIGEST,'decision':'granted','approver':'approver-primary'}
EFFECT={'kind':'effect','operation':'cancel-and-refund','order_id':'ORD-1001','idempotency_key':'cancel-and-refund:ORD-1001','effect_status':'EFFECT_COMPLETED','duplicate':False}

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='br-m5-audit-'))
        self.addCleanup(self._cleanup)
    def _cleanup(self):
        shutil.rmtree(self.root,ignore_errors=True)
    def test_audit_is_append_only_and_preserves_order(self):
        writer=AuditWriter(self.root)
        self.assertEqual(writer.records(),[])
        writer.append(APPROVAL)
        after_first=writer.path().read_text(encoding='utf-8')
        writer.append(EFFECT)
        after_second=writer.path().read_text(encoding='utf-8')
        self.assertTrue(after_second.startswith(after_first))
        self.assertEqual(len([line for line in after_second.split('\n') if line.strip()]),2)
        self.assertEqual(writer.records(),[APPROVAL,EFFECT])
        reopened=AuditWriter(self.root)
        reopened.append({**APPROVAL,'decision':'rejected'})
        self.assertEqual(len(writer.records()),3)
        self.assertEqual(writer.records()[2],{**APPROVAL,'decision':'rejected'})
    def test_audit_rejects_invalid_records_without_writing_them(self):
        writer=AuditWriter(self.root)
        bad=[{**APPROVAL,'decision':'approved'},{**APPROVAL,'extra':1},{**APPROVAL,'payload_digest':'zz'},
             {**APPROVAL,'approver':''},{**EFFECT,'effect_status':'EFFECT_LANDED'},{**EFFECT,'duplicate':'no'},
             {**EFFECT,'payload_digest':DIGEST},{**APPROVAL,'idempotency_key':'k'},
             {'kind':'approval','operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':DIGEST,'decision':'granted'}]
        for record in bad:
            with self.assertRaises(ValueError):writer.append(record)
        self.assertEqual(writer.records(),[])
        self.assertFalse(writer.path().exists())

