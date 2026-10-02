import copy
import unittest
import yaml

from boundrelay_m2.scenario import load_scenario, find_scenario_case, load_failure_fixtures
from boundrelay_m2.schemas import validate_handoff, validate_route_decision
from boundrelay_m2.policy import apply_confidence_policy
from boundrelay_m2.scripted_router import classify_with_code, ScriptedRouteProvider
from boundrelay_m2.receivers import create_receiver_directory
from boundrelay_m2.types import RouteDecision, ReceiverInput
from boundrelay_m2.paths import SCENARIO_PATH, FAILURE_PATH


class Foundations(unittest.IsolatedAsyncioTestCase):
    def test_scenario_and_failure_isolation(self):
        case = find_scenario_case(load_scenario(), 'model-low-confidence-fallback')
        self.assertEqual((case.router_mode, case.expected_proposed_route, case.expected_confidence, case.expected_selected_route, case.expected_receiver, case.expected_fallback_applied), ('model', 'billing', .54, 'general', 'general-specialist', True))
        self.assertEqual(set(load_failure_fixtures()), {'handoff-context-loss', 'handoff-receiver-unavailable'})
        self.assertNotIn('code-billing-handoff', load_failure_fixtures())

    def test_scenario_noncoercing_validation(self):
        raw = yaml.safe_load(SCENARIO_PATH.read_text(encoding='utf-8'))
        for threshold in ('0.80', True, .79):
            with self.assertRaises(ValueError): load_scenario({**raw, 'confidence_threshold': threshold})
        with self.assertRaises(ValueError): load_scenario({**raw, 'cases': [*raw['cases'], raw['cases'][0]]})
        for key, value in [('router_mode','auto'), ('expected_fallback_applied','false'), ('ticket_id','bad'), ('failure_ref','unknown')]:
            bad = copy.deepcopy(raw)
            bad['cases'][0][key] = value
            with self.assertRaises(ValueError): load_scenario(bad)
        failures = yaml.safe_load(FAILURE_PATH.read_text(encoding='utf-8'))
        failures['failures']['handoff-context-loss']['retry'] = True
        with self.assertRaises(ValueError): load_failure_fixtures(failures)

    def test_strict_context_and_route_schema(self):
        base = {'schema_version': '1.0', 'handoff_id': 'h', 'sender': 'support-router', 'receiver': 'billing-specialist', 'sender_intent': {'route': 'billing', 'confidence': .8, 'policy_outcome': 'selected'}, 'receiver_input': {'ticket_id': 'TCK-1001', 'request_text': 'invoice'}}
        self.assertTrue(validate_handoff(base).ok)
        for context in ({'ticket_id': 'TCK-1001'}, {**base['receiver_input'], 'prompt': 'secret'}):
            self.assertFalse(validate_handoff({**base, 'receiver_input': context}).ok)
        for confidence in (float('nan'), float('inf'), '0.8', True, -1, 2, 10**1000):
            self.assertFalse(validate_route_decision({'route': 'billing', 'confidence': confidence}).ok)
        self.assertFalse(validate_route_decision({'route': 'billing', 'confidence': .8, 'receiver': 'general-specialist'}).ok)

    def test_threshold_equality_and_fixed_mapping(self):
        equal = apply_confidence_policy(RouteDecision('billing', .8))
        self.assertEqual((equal.selected_route, equal.receiver, equal.policy_outcome, equal.fallback_applied), ('billing','billing-specialist','selected',False))
        fallback = apply_confidence_policy(RouteDecision('billing', .79))
        self.assertEqual((fallback.selected_route, fallback.receiver, fallback.policy_outcome, fallback.fallback_applied), ('general','general-specialist','fallback',True))
        for route in ('technical','general'):
            self.assertEqual(apply_confidence_policy(RouteDecision(route, 1)).receiver, route+'-specialist')

    def test_code_baseline(self):
        self.assertEqual(classify_with_code('I was billed twice'), RouteDecision('billing', 1))
        self.assertEqual(classify_with_code('The app is broken').route, 'technical')
        self.assertEqual(classify_with_code('Hello').route, 'general')

    async def test_scripted_consumption_and_receivers(self):
        provider = ScriptedRouteProvider.from_file()
        self.assertEqual(await provider.next_decision(case_id='model-technical-handoff', request='ignored'), {'route': 'technical', 'confidence': .92})
        for case_id in ('model-technical-handoff','unknown'):
            with self.assertRaises(ValueError): await provider.next_decision(case_id=case_id, request='invoice')
        directory = create_receiver_directory(('billing-specialist',))
        self.assertIsNone(directory.resolve('billing-specialist'))
        self.assertIsNone(directory.resolve('unknown'))
        for name in ('technical-specialist','general-specialist'):
            await directory.resolve(name).handle(ReceiverInput('TCK-1001','hello'))
