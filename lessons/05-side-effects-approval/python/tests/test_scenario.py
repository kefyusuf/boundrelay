import unittest
import yaml
from boundrelay_m5.paths import SCENARIO_PATH
from boundrelay_m5.scenario import load_scenario,parse_scenario,load_worker_fixture

def raw():
    return yaml.safe_load(SCENARIO_PATH.read_text(encoding='utf-8'))

class ScenarioTests(unittest.TestCase):
    def test_loads_six_canonical_cases_with_approval_and_control_metadata(self):
        s=load_scenario()
        self.assertEqual(s.scenario_id,'order-closure');self.assertEqual(len(s.cases),6)
        by={c.case_id:c for c in s.cases}
        self.assertEqual(by['approval-granted-effect-once'].approval,{'decision':'granted','approver':'approver-primary'})
        self.assertEqual(by['approval-rejected-no-effect'].approval,{'decision':'rejected','approver':'approver-primary'})
        self.assertEqual(by['retry-before-submit'].controls,{'crash_before_submit':True})
        self.assertEqual(by['crash-submit-window-resolved'].controls,{'crash_in_submit_window':True})
        self.assertEqual(by['sink-unavailable-unknown'].controls,{'crash_in_submit_window':True,'sink_unavailable':True})
        self.assertTrue(by['duplicate-key-suppressed'].duplicate_key)
        for case_id in ('approval-granted-effect-once','approval-rejected-no-effect'):
            self.assertIsNone(by[case_id].controls);self.assertFalse(by[case_id].duplicate_key)
        for c in s.cases:
            self.assertEqual(list(c.completion_order),['order-details','payment-status','delivery-status'])
    def test_rejects_control_grammar_violations(self):
        unknown=raw();unknown['cases'][2]['controls']={'crash_before':'order-details'}
        with self.assertRaisesRegex(ValueError,'Unknown control field'):parse_scenario(unknown)
        mixed=raw();mixed['cases'][2]['controls']={'crash_before_submit':True,'crash_in_submit_window':True}
        with self.assertRaisesRegex(ValueError,'Invalid control combination'):parse_scenario(mixed)
        both=raw();both['cases'][3]['controls']={'crash_in_submit_window':True,'sink_unavailable':True}
        with self.assertRaisesRegex(ValueError,'Invalid control combination'):parse_scenario(both)
        sink_alone=raw();sink_alone['cases'][3]['controls']={'sink_unavailable':True}
        with self.assertRaisesRegex(ValueError,'Invalid control combination'):parse_scenario(sink_alone)
        wrong_case=raw();wrong_case['cases'][0]['controls']={'crash_before_submit':True}
        with self.assertRaisesRegex(ValueError,'Invalid controls for case'):parse_scenario(wrong_case)
        extra=raw();extra['cases'][0]['unexpected']='field'
        with self.assertRaisesRegex(ValueError,'Invalid case fields'):parse_scenario(extra)
        false_flag=raw();false_flag['cases'][2]['controls']={'crash_before_submit':False}
        with self.assertRaisesRegex(ValueError,'Invalid control value'):parse_scenario(false_flag)
    def test_rejects_invalid_approval_blocks(self):
        bad_decision=raw();bad_decision['cases'][0]['approval']={'decision':'approved','approver':'approver-primary'}
        with self.assertRaisesRegex(ValueError,'Invalid approval decision'):parse_scenario(bad_decision)
        empty_approver=raw();empty_approver['cases'][0]['approval']={'decision':'granted','approver':''}
        with self.assertRaisesRegex(ValueError,'Invalid approver'):parse_scenario(empty_approver)
        missing=raw();del missing['cases'][0]['approval']
        with self.assertRaisesRegex(ValueError,'Invalid case fields'):parse_scenario(missing)
        extra=raw();extra['cases'][0]['approval']={'decision':'granted','approver':'a','reason':'why'}
        with self.assertRaisesRegex(ValueError,'Invalid approval block'):parse_scenario(extra)
    def test_rejects_duplicate_key_misuse_and_fixture_escapes(self):
        wrong_case=raw();wrong_case['cases'][0]['duplicate_key']=True
        with self.assertRaisesRegex(ValueError,'Invalid duplicate_key'):parse_scenario(wrong_case)
        false_flag=raw();false_flag['cases'][5]['duplicate_key']=False
        with self.assertRaisesRegex(ValueError,'Invalid duplicate_key'):parse_scenario(false_flag)
        with self.assertRaisesRegex(ValueError,'Worker fixture escapes root'):
            load_worker_fixture('fixtures/workers/order-brief/../../../../outside.yaml')
        with self.assertRaises(ValueError):parse_scenario({'schema_version':'2.0'})


