from copy import deepcopy
from pathlib import Path
import re
import yaml
from .paths import ROOT,SCENARIO_PATH
from .types import WORKER_IDS,CaseSpec,Scenario

def fields(raw,keys):
    if type(raw) is not dict or set(raw)!=set(keys):raise ValueError('Invalid fixture fields')
    return raw

def load_worker_fixture(path):
    if type(path) is not str:raise ValueError('Invalid fixture path')
    target=(ROOT/path).resolve();base=(ROOT/'fixtures/workers/order-brief').resolve()
    if not target.is_relative_to(base):raise ValueError('Worker fixture escapes root')
    raw=fields(yaml.safe_load(target.read_text(encoding='utf-8')),WORKER_IDS)
    for instruction in raw.values():
        if type(instruction) is not dict:raise ValueError('Invalid worker instruction')
        if instruction.get('operation')=='return':fields(instruction,['operation','output'])
        elif instruction.get('operation')=='raise' and instruction.get('failure_code')=='WORKER_EXECUTION_FAILED':fields(instruction,['operation','failure_code'])
        else:raise ValueError('Invalid worker operator')
    return deepcopy(raw)

def parse_scenario(raw):
    s=fields(raw,['schema_version','scenario_id','order_id','cases'])
    if s['schema_version']!='1.0' or s['scenario_id']!='order-brief' or type(s['order_id']) is not str or re.fullmatch(r'ORD-[0-9]{4}',s['order_id']) is None or type(s['cases']) is not list or len(s['cases'])!=6:raise ValueError('Invalid scenario')
    seen=set();cases=[]
    for c in s['cases']:
        fields(c,['case_id','execution_mode','worker_fixture','completion_order'])
        if type(c['case_id']) is not str or not c['case_id'] or c['case_id'] in seen or c['execution_mode'] not in ('sequential','parallel'):raise ValueError('Invalid case')
        seen.add(c['case_id']);load_worker_fixture(c['worker_fixture'])
        order=c['completion_order']
        if type(order) is not list or len(order)!=3 or any(type(v) is not str for v in order) or sorted(order)!=sorted(WORKER_IDS):raise ValueError('Invalid completion permutation')
        active=set();pending=list(WORKER_IDS);limit=1 if c['execution_mode']=='sequential' else 2
        for next_id in order:
            while len(active)<limit and pending:active.add(pending.pop(0))
            if next_id not in active:raise ValueError('Infeasible completion schedule')
            active.remove(next_id)
        cases.append(CaseSpec(c['case_id'],c['execution_mode'],c['worker_fixture'],tuple(order)))
    return Scenario('1.0','order-brief',s['order_id'],tuple(cases))

def load_scenario():
    return parse_scenario(yaml.safe_load(SCENARIO_PATH.read_text(encoding='utf-8')))
