import unittest
from boundrelay_m5.approval import ApprovalGate,require_approval
from boundrelay_m5.idempotency import effect_digest

PAYLOAD={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}

class ApprovalTests(unittest.TestCase):
    def test_approval_binds_to_payload_digest(self):
        gate=ApprovalGate({'decision':'granted','approver':'approver-primary'})
        granted=gate.decide(PAYLOAD)
        self.assertEqual(granted['decision'],'granted')
        self.assertEqual(granted['record'],{'operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':effect_digest(PAYLOAD),'decision':'granted','approver':'approver-primary'})
        rejected=ApprovalGate({'decision':'rejected','approver':'approver-primary'}).decide(PAYLOAD)
        self.assertEqual(rejected['decision'],'rejected')
        self.assertEqual(rejected['record']['decision'],'rejected')
        self.assertEqual(rejected['record']['payload_digest'],effect_digest(PAYLOAD))
        with self.assertRaisesRegex(ValueError,'Approval not granted'):
            require_approval(rejected['record'],PAYLOAD)
    def test_require_approval_raises_on_binding_mismatch(self):
        gate=ApprovalGate({'decision':'granted','approver':'approver-primary'})
        record=gate.decide(PAYLOAD)['record']
        require_approval(record,PAYLOAD)
        with self.assertRaisesRegex(ValueError,'Approval binding mismatch'):
            require_approval({**record,'payload_digest':'d'*64},PAYLOAD)
        with self.assertRaisesRegex(ValueError,'Approval binding mismatch'):
            require_approval({**record,'operation':'cancel'},PAYLOAD)
        with self.assertRaisesRegex(ValueError,'Approval binding mismatch'):
            require_approval({**record,'order_id':'ORD-1002'},PAYLOAD)
