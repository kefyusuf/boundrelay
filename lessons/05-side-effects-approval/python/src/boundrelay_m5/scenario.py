from copy import deepcopy
import re
import yaml
from .paths import ROOT,SCENARIO_PATH
from .types import WORKER_IDS,CaseSpec,Scenario

CASE_BASE=('case_id','execution_mode','worker_fixture','completion_order')
CASE_OPTIONAL=('approval','controls','duplicate_key')
APPROVAL_DECISIONS=('granted','rejected')
CONTROL_FIELDS=('crash_before_submit','crash_in_submit_window','sink_unavailable')
CANONICAL_CONTROLS={'approval-granted-effect-once':(),'approval-rejected-no-effect':(),'retry-before-submit':('crash_before_submit',),'crash-submit-window-resolved':('crash_in_submit_window',),'sink-unavailable-unknown':('crash_in_submit_window','sink_unavailable'),'duplicate-key-suppressed':()}

def fields(raw,keys):
    if type(raw) is not dict or set(raw)!=set(keys):raise ValueError('Invalid fixture fields')
    return raw

STEP_KINDS=('read','model_decision','tool_call','effect','handoff','route','synthesis')

def parse_attribution(raw):
    if raw is None:return None
    fields(raw,['latency_ms','price_table'])
    latency,prices=raw['latency_ms'],raw['price_table']
    if type(latency) is not dict or not latency or any(not k or type(v) is not int or v<0 for k,v in latency.items()):raise ValueError('Invalid scenario')
    if type(prices) is not dict or not prices or any(k not in STEP_KINDS or type(v) is not int or v<0 for k,v in prices.items()):raise ValueError('Invalid scenario')
    if prices.get('read',1)!=0:raise ValueError('Invalid scenario')
    return {'latency_ms':dict(latency),'price_table':dict(prices)}

def case_fields(raw):
    if type(raw) is not dict:raise ValueError('Invalid case fields')
    keys=set(raw)
    if not set(CASE_BASE)<=keys or not keys<=set(CASE_BASE)|set(CASE_OPTIONAL):raise ValueError('Invalid case fields')
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

def parse_approval(raw)->dict[str,object]:
    if type(raw) is not dict or set(raw)!=set(('decision','approver')):raise ValueError('Invalid approval block')
    if raw['decision'] not in APPROVAL_DECISIONS:raise ValueError('Invalid approval decision')
    if type(raw['approver']) is not str or not raw['approver']:raise ValueError('Invalid approver')
    return {'decision':raw['decision'],'approver':raw['approver']}

def parse_controls(raw,case_id:str)->dict[str,bool]:
    if type(raw) is not dict or not raw:raise ValueError('Invalid controls')
    fields=tuple(sorted(raw))
    for name in fields:
        if name not in CONTROL_FIELDS:raise ValueError('Unknown control field')
        if raw[name] is not True:raise ValueError('Invalid control value')
    if 'crash_before_submit' in fields and len(fields)>1:raise ValueError('Invalid control combination')
    if 'sink_unavailable' in fields and ('crash_in_submit_window' not in fields or case_id!='sink-unavailable-unknown'):raise ValueError('Invalid control combination')
    if fields!=tuple(sorted(CANONICAL_CONTROLS.get(case_id,('?',)))):raise ValueError(f'Invalid controls for case {case_id}')
    return dict(raw)

def parse_scenario(raw)->Scenario:
    s=fields(raw,['schema_version','scenario_id','order_id','cases']+(['attribution'] if type(raw) is dict and 'attribution' in raw else []))
    parse_attribution(s.get('attribution'))
    if s['schema_version']!='1.0' or s['scenario_id']!='order-closure' or type(s['order_id']) is not str or re.fullmatch(r'ORD-[0-9]{4}',s['order_id']) is None or type(s['cases']) is not list or len(s['cases'])!=6:raise ValueError('Invalid scenario')
    seen=set();cases=[]
    for c in s['cases']:
        case_fields(c)
        if type(c['case_id']) is not str or not c['case_id'] or c['case_id'] in seen or c['execution_mode'] not in ('sequential','parallel') or type(c['worker_fixture']) is not str:raise ValueError('Invalid case')
        seen.add(c['case_id']);load_worker_fixture(c['worker_fixture'])
        if 'approval' not in c:raise ValueError('Invalid case fields')
        approval=parse_approval(c['approval'])
        order=c['completion_order']
        if type(order) is not list or len(order)!=3 or any(type(v) is not str for v in order) or sorted(order)!=sorted(WORKER_IDS):raise ValueError('Invalid completion permutation')
        controls=parse_controls(c['controls'],c['case_id']) if 'controls' in c else None
        if 'duplicate_key' in c and (c['case_id']!='duplicate-key-suppressed' or c['duplicate_key'] is not True):raise ValueError('Invalid duplicate_key')
        cases.append(CaseSpec(c['case_id'],c['execution_mode'],c['worker_fixture'],tuple(order),approval,controls,'duplicate_key' in c))
        active=set();pending=list(WORKER_IDS);limit=1 if c['execution_mode']=='sequential' else 2
        for next_id in order:
            while len(active)<limit and pending:active.add(pending.pop(0))
            if next_id not in active:raise ValueError('Infeasible completion schedule')
            active.remove(next_id)
    return Scenario('1.0','order-closure',s['order_id'],tuple(cases))

def load_scenario()->Scenario:
    return parse_scenario(yaml.safe_load(SCENARIO_PATH.read_text(encoding='utf-8')))


