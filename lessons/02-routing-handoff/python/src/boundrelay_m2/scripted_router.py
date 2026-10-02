from copy import deepcopy
import yaml
from .paths import MODEL_PATH
from .scenario import load_scenario
from .types import RouteDecision


def classify_with_code(request: str) -> RouteDecision:
    text = request.lower()
    route = 'billing' if any(k in text for k in ('charged','charge','invoice','payment','refund','billed')) else 'technical' if any(k in text for k in ('error','crash','cannot log in',"can't log in",'bug','broken')) else 'general'
    return RouteDecision(route, 1.0)


class ScriptedRouteError(ValueError): pass


class ScriptedRouteProvider:
    def __init__(self, decisions):
        self._decisions = deepcopy(decisions)
        self._consumed = set()

    @classmethod
    def from_file(cls):
        raw = yaml.safe_load(MODEL_PATH.read_text(encoding='utf-8'))
        expected = {c.id for c in load_scenario().cases if c.router_mode == 'model'}
        if not isinstance(raw, dict) or set(raw) != {'schema_version','scenario_id','decisions'} or raw['schema_version'] != '1.0' or raw['scenario_id'] != 'support-handoff' or not isinstance(raw['decisions'],dict) or set(raw['decisions']) != expected or any(not isinstance(v,dict) or set(v) != {'return'} for v in raw['decisions'].values()):
            raise ScriptedRouteError('Invalid model fixtures')
        return cls(raw['decisions'])

    async def next_decision(self, *, case_id: str, request: str) -> object:
        if case_id not in self._decisions or case_id in self._consumed: raise ScriptedRouteError(f'Missing or consumed decision: {case_id}')
        self._consumed.add(case_id)
        return deepcopy(self._decisions[case_id]['return'])
