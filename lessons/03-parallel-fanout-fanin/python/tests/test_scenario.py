from copy import deepcopy
import unittest
import yaml
from boundrelay_m3.paths import SCENARIO_PATH
from boundrelay_m3.scenario import load_scenario,parse_scenario,load_worker_fixture
class ScenarioTests(unittest.TestCase):
    def test_reject_infeasible_schedule(self):
        raw=yaml.safe_load(SCENARIO_PATH.read_text())
        for order in [['payment-status','order-details','delivery-status'],['order-details','order-details','delivery-status'],['order-details','payment-status'],['unknown','payment-status','delivery-status']]:
            bad=deepcopy(raw);bad['cases'][0]['completion_order']=order
            with self.assertRaises(ValueError):parse_scenario(bad)
        bad=deepcopy(raw);bad['cases'][1]['completion_order']=['delivery-status','order-details','payment-status']
        with self.assertRaises(ValueError):parse_scenario(bad)
        bad=deepcopy(raw);bad['cases'][1]['case_id']=bad['cases'][0]['case_id']
        with self.assertRaises(ValueError):parse_scenario(bad)
    def test_invalid_return_reaches_runtime_validation(self):
        scenario=load_scenario();self.assertEqual(len(scenario.cases),6)
        case=next(c for c in scenario.cases if c.case_id=='parallel-invalid-output')
        self.assertEqual(load_worker_fixture(case.worker_fixture)['payment-status'],{'operation':'return','output':{'order_id':'ORD-1001','payment_status':'UNKNOWN'}})
