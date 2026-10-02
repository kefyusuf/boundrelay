from copy import deepcopy
import yaml
from jsonschema import Draft202012Validator
from .paths import SCENARIO_PATH, FAILURE_PATH
from .policy import ROUTE_RECEIVERS
from .types import ScenarioCase, ScenarioDefinition


def _obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}


_str = {'type': 'string', 'minLength': 1}
_bool = {'type': 'boolean'}
_header = {'schema_version': {'const': '1.0'}, 'scenario_id': {'const': 'support-handoff'}}
_route = {'enum': list(ROUTE_RECEIVERS)}
_case_fields = {'id': _str, 'ticket_id': {'type': 'string', 'pattern': '^TCK-[0-9]{4}$'}, 'request': _str, 'router_mode': {'enum': ['code', 'model']}, 'expected_status': {'enum': ['SUCCEEDED', 'FAILED']}, 'expected_proposed_route': _route, 'expected_confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'expected_selected_route': _route, 'expected_receiver': {'enum': list(ROUTE_RECEIVERS.values())}, 'expected_policy_outcome': {'enum': ['selected', 'fallback']}, 'expected_fallback_applied': _bool, 'expected_specialist_invoked': _bool, 'expected_failure_code': {'enum': [None, 'HANDOFF_CONTEXT_INVALID', 'HANDOFF_RECEIVER_UNAVAILABLE']}, 'failure_ref': _str}
_scenario = Draft202012Validator(_obj({**_header, 'confidence_threshold': {'const': .8}, 'route_receivers': _obj({k: {'const': v} for k,v in ROUTE_RECEIVERS.items()}), 'cases': {'type': 'array', 'minItems': 5, 'maxItems': 5, 'items': _obj(_case_fields, [k for k in _case_fields if k != 'failure_ref'])}}))
_failures = Draft202012Validator(_obj({**_header, 'failures': _obj({'handoff-context-loss': _obj({'omit_receiver_input_fields': {'const': ['request_text']}}), 'handoff-receiver-unavailable': _obj({'unavailable_receivers': {'const': ['billing-specialist']}})})}))


def load_failure_fixtures(raw=None):
    if raw is None: raw = yaml.safe_load(FAILURE_PATH.read_text(encoding='utf-8'))
    if not _failures.is_valid(raw): raise ValueError('Invalid M2 failure fixtures')
    return deepcopy(raw['failures'])


def load_scenario(raw=None) -> ScenarioDefinition:
    if raw is None: raw = yaml.safe_load(SCENARIO_PATH.read_text(encoding='utf-8'))
    if not _scenario.is_valid(raw): raise ValueError('Invalid M2 scenario')
    expected = {'code-billing-handoff','model-technical-handoff','model-low-confidence-fallback','handoff-context-loss','handoff-receiver-unavailable'}
    for case in raw['cases']:
        if case['id'] not in expected: raise ValueError('Duplicate or unknown M2 case')
        expected.remove(case['id'])
        if case['id'].startswith('handoff-'):
            if case.get('failure_ref') != case['id']: raise ValueError('Invalid M2 failure reference')
        elif 'failure_ref' in case: raise ValueError('Invalid M2 failure reference')
    return ScenarioDefinition(raw['schema_version'],raw['scenario_id'],raw['confidence_threshold'],deepcopy(raw['route_receivers']),tuple(ScenarioCase(**c) for c in raw['cases']))


def find_scenario_case(scenario, case_id):
    for case in scenario.cases:
        if case.id == case_id: return case
    raise ValueError(f'Unknown case: {case_id}')
