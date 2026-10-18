import unittest
from boundrelay_m3.schemas import validate_worker_output
class SchemaTests(unittest.TestCase):
    def test_reject_original_invalid_output(self):
        valid={'order_id':'ORD-1001','payment_status':'PAID'}
        accepted=validate_worker_output('payment-status',valid,'ORD-1001')
        self.assertTrue(accepted.valid)
        self.assertEqual(accepted.value,valid)
        cycle={};cycle['self']=cycle
        for raw in [{**valid,'private':'secret'},{**valid,'order_id':'ORD-9999'},
                    {**valid,'payment_status':'UNKNOWN'},float('nan'),float('inf'),cycle,{**valid,'n':10**10000}]:
            rejected=validate_worker_output('payment-status',raw,'ORD-1001')
            self.assertFalse(rejected.valid)
            self.assertIsNone(rejected.value)
