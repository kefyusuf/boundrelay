from copy import deepcopy
import unittest
import yaml
from boundrelay_m4.paths import SCENARIO_PATH
from boundrelay_m4.scenario import load_scenario,parse_scenario,load_worker_fixture
from boundrelay_m4.types import RecoveryControls

def raw():
    return yaml.safe_load(SCENARIO_PATH.read_text())

class ScenarioTests(unittest.TestCase):
    def test_loads_six_canonical_cases_with_recovery_metadata(self):
        s=load_scenario()
        self.assertEqual(s.scenario_id,'order-brief-recovery');self.assertEqual(len(s.cases),6)
        by={c.case_id:c for c in s.cases}
        self.assertEqual(by['parallel-crash-resume'].controls,RecoveryControls(crash_after='payment-status'))
        self.assertEqual(by['parallel-crash-resume-partial'].controls,RecoveryControls(crash_after='delivery-status'))
        self.assertEqual(by['parallel-cancel-resume'].controls,RecoveryControls(cancel_before='delivery-status'))
        self.assertEqual(by['parallel-replay-from-checkpoint'].replay_from_step,1)
        self.assertEqual(by['parallel-corrupt-state'].tampered_state,'flip_payment_outcome')
        self.assertIsNone(by['parallel-clean-complete'].controls)
        for c in s.cases:
            self.assertEqual(list(c.completion_order),['order-details','payment-status','delivery-status'])
    def test_rejects_control_grammar_violations(self):
        two=raw();two['cases'][3]['controls']={'crash_after':'order-details','cancel_before':'delivery-status'}
        with self.assertRaises(ValueError):parse_scenario(two)
        unknown=raw();unknown['cases'][3]['controls']={'crash_before':'delivery-status'}
        with self.assertRaisesRegex(ValueError,'Unknown control field'):parse_scenario(unknown)
        bad_target=raw();bad_target['cases'][3]['controls']={'crash_after':'unknown-worker'}
        with self.assertRaisesRegex(ValueError,'Invalid control target'):parse_scenario(bad_target)
        extra=raw();extra['cases'][3]['unexpected']='field'
        with self.assertRaisesRegex(ValueError,'Invalid case fields'):parse_scenario(extra)
    def test_rejects_infeasible_crash_and_cancel_targets(self):
        first=raw();first['cases'][0]['controls']={'crash_after':'order-details'}
        with self.assertRaisesRegex(ValueError,'Infeasible crash target'):parse_scenario(first)
        bad_cancel=raw();bad_cancel['cases'][0]['controls']={'cancel_before':'payment-status'}
        with self.assertRaisesRegex(ValueError,'Infeasible cancel target'):parse_scenario(bad_cancel)
    def test_rejects_replay_and_tamper_misuse(self):
        with_control=raw();with_control['cases'][4]['controls']={'crash_after':'payment-status'}
        with self.assertRaises(ValueError):parse_scenario(with_control)
        bad_range=raw();bad_range['cases'][4]['replay_from_step']=4
        with self.assertRaisesRegex(ValueError,'Invalid replay_from_step'):parse_scenario(bad_range)
        bad_tamper=raw();bad_tamper['cases'][5]['tampered_state']='other'
        with self.assertRaisesRegex(ValueError,'Invalid tampered_state'):parse_scenario(bad_tamper)
    def test_rejects_combined_replay_and_tamper_metadata(self):
        both=raw();both['cases'][4]['replay_from_step']=1;both['cases'][4]['tampered_state']='flip_payment_outcome'
        with self.assertRaisesRegex(ValueError,'Invalid control combination'):parse_scenario(both)
    def test_reject_worker_fixture_paths_escaping_the_reused_directory(self):
        with self.assertRaisesRegex(ValueError,'Worker fixture escapes root'):
            load_worker_fixture('fixtures/workers/order-brief/../../../../outside.yaml')
