from copy import deepcopy
import unittest
from boundrelay_m3.collector import canonicalize_outcomes
from boundrelay_m3.synthesizer import synthesize_brief
from tools.contracts.test_m3_contracts import outcome
class SynthesisTests(unittest.TestCase):
    def test_canonical_merge_ignores_completion_order(self):
        outcomes=tuple(outcome(i) for i in range(3))
        self.assertEqual(canonicalize_outcomes(list(reversed(outcomes)),'ORD-1001'),outcomes)
        brief=synthesize_brief('ORD-1001',outcomes)
        self.assertEqual([s['worker_id'] for s in brief['sections']],['order-details','payment-status','delivery-status'])
        self.assertTrue(brief['complete']);self.assertEqual(brief['missing_workers'],[])
        brief['sections'][0]['output']['order_id']='ORD-9999';self.assertEqual(outcomes[0]['output']['order_id'],'ORD-1001')
    def test_reject_incomplete_or_duplicate_fanin(self):
        outcomes=[outcome(i) for i in range(3)]
        wrong=deepcopy(outcomes);wrong[0]['output']['order_id']='ORD-9999'
        for raw in [[outcomes[0]],[outcomes[0],outcomes[0],outcomes[2]],outcomes+[{'worker_id':'unknown'}],wrong]:
            with self.assertRaises(ValueError):canonicalize_outcomes(raw,'ORD-1001')
    def test_failed_reads_do_not_fabricate_sections(self):
        brief=synthesize_brief('ORD-1001',(outcome(0),outcome(1,True),outcome(2,True)))
        self.assertEqual([s['worker_id'] for s in brief['sections']],['order-details'])
        self.assertEqual(brief['missing_workers'],['payment-status','delivery-status']);self.assertFalse(brief['complete'])
        with self.assertRaises(ValueError):synthesize_brief('ORD-1001',tuple(outcome(i,True) for i in range(3)))
