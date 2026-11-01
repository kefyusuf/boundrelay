from copy import deepcopy
import re
import yaml
from .paths import ROOT,SCENARIO_PATH
from .types import WORKER_IDS,CaseSpec,RecoveryControls,Scenario,WorkerId

CASE_BASE=('case_id','execution_mode','worker_fixture','completion_order')
CASE_OPTIONAL=('controls','replay_from_step','tampered_state')

def fields(raw,keys):
    if type(raw) is not dict or set(raw)!=set(keys):raise ValueError('Invalid fixture fields')
    return raw

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

def parse_controls(raw,completion:list[str])->RecoveryControls:
    if type(raw) is not dict or len(raw)!=1:raise ValueError('Invalid controls')
    ((key,target),)=raw.items()
    if key not in ('crash_after','cancel_before'):raise ValueError('Unknown control field')
    if type(target) is not str or target not in WORKER_IDS:raise ValueError('Invalid control target')
    if key=='crash_after':
        prefix=WORKER_IDS[:WORKER_IDS.index(target)+1]
        pos={worker_id:completion.index(worker_id) for worker_id in WORKER_IDS}
        if len(prefix)<2 or any(worker_id!=target and pos[worker_id]>pos[target] for worker_id in prefix):raise ValueError('Infeasible crash target')
        return RecoveryControls(crash_after=target)
    if target!=WORKER_IDS[-1]:raise ValueError('Infeasible cancel target')
    return RecoveryControls(cancel_before=target)

def parse_scenario(raw)->Scenario:
    s=fields(raw,['schema_version','scenario_id','order_id','cases'])
    if s['schema_version']!='1.0' or s['scenario_id']!='order-brief-recovery' or type(s['order_id']) is not str or re.fullmatch(r'ORD-[0-9]{4}',s['order_id']) is None or type(s['cases']) is not list or len(s['cases'])!=6:raise ValueError('Invalid scenario')
    seen=set();cases=[]
    for c in s['cases']:
        case_fields(c)
        if type(c['case_id']) is not str or not c['case_id'] or c['case_id'] in seen or c['execution_mode'] not in ('sequential','parallel') or type(c['worker_fixture']) is not str:raise ValueError('Invalid case')
        seen.add(c['case_id']);load_worker_fixture(c['worker_fixture'])
        order=c['completion_order']
        if type(order) is not list or len(order)!=3 or any(type(v) is not str for v in order) or sorted(order)!=sorted(WORKER_IDS):raise ValueError('Invalid completion permutation')
        if sum(1 for name in CASE_OPTIONAL if name in c)>1:raise ValueError('Invalid control combination')
        controls=parse_controls(c['controls'],order) if 'controls' in c else None
        replay_from_step=None
        if 'replay_from_step' in c:
            value=c['replay_from_step']
            if type(value) is not int or isinstance(value,bool) or not 1<=value<=3:raise ValueError('Invalid replay_from_step')
            replay_from_step=value
        tampered_state=None
        if 'tampered_state' in c:
            if c['tampered_state']!='flip_payment_outcome':raise ValueError('Invalid tampered_state')
            tampered_state=c['tampered_state']
        cases.append(CaseSpec(c['case_id'],c['execution_mode'],c['worker_fixture'],tuple(order),controls,replay_from_step,tampered_state))
        active=set();pending=list(WORKER_IDS);limit=1 if c['execution_mode']=='sequential' else 2
        for next_id in order:
            while len(active)<limit and pending:active.add(pending.pop(0))
            if next_id not in active:raise ValueError('Infeasible completion schedule')
            active.remove(next_id)
    return Scenario('1.0','order-brief-recovery',s['order_id'],tuple(cases))

def load_scenario()->Scenario:
    return parse_scenario(yaml.safe_load(SCENARIO_PATH.read_text(encoding='utf-8')))
