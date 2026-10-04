from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .normalize import normalize_event,normalize_result,read_jsonl
from .verify_m2 import assert_clean_worktree,_revision

ROOT=Path(__file__).resolve().parents[2]
PY_SRC=ROOT/'lessons/03-parallel-fanout-fanin/python/src'
TS_ROOT=ROOT/'lessons/03-parallel-fanout-fanin/typescript'
OUTPUT_ROOT=ROOT/'.boundrelay/m3'
EVIDENCE_PATH=OUTPUT_ROOT/'verification-evidence.json'
sys.path.insert(0,str(PY_SRC))
from boundrelay_m3.types import WORKER_IDS
from boundrelay_m3.schemas import EVENT_VALIDATOR,RESULT_VALIDATOR,WORKER_VALIDATOR,finite_json
from boundrelay_m3.scenario import load_scenario,load_worker_fixture

REQUIRED_PROBES=('parallel_calls_overlap_without_exceeding_two','sequential_never_overlaps',
                 'declared_failures_do_not_retry','unexpected_error_drains_without_admitting_queued_worker')
TERMINAL_KEYS=('status','worker_outcomes','synthesis_invoked','brief','failure_code','peak_concurrency')

def require(condition,message):
    if not condition:raise AssertionError(message)

def clear_previous_evidence():
    target=OUTPUT_ROOT.resolve()
    if target.name!='m3' or target in (ROOT.resolve(),ROOT.parent.resolve()):raise RuntimeError('Unsafe evidence root')
    if target.exists():shutil.rmtree(target)

def validate_lower_evidence(revision):
    for milestone in ('m0','m1','m2'):
        path=ROOT/f'.boundrelay/{milestone}/verification-evidence.json'
        proof=json.loads(path.read_text(encoding='utf-8'))
        if proof.get('status')!='PASSED' or proof.get('revision')!=revision:raise RuntimeError(f'{milestone} evidence is stale or failed')

def publish_evidence(evidence,starting_revision):
    assert_clean_worktree()
    if _revision()!=starting_revision:raise RuntimeError('HEAD moved during verification')
    if evidence.get('revision')!=starting_revision or evidence.get('status')!='PASSED':raise RuntimeError('Invalid evidence identity')
    validate_lower_evidence(starting_revision)
    EVIDENCE_PATH.parent.mkdir(parents=True,exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def expected_case(case):
    instructions=load_worker_fixture(case['worker_fixture']);outcomes=[]
    for worker_id in WORKER_IDS:
        instruction=instructions[worker_id]
        candidate={'worker_id':worker_id,'status':'SUCCEEDED','output':instruction.get('output'),'failure_code':None}
        valid=finite_json(candidate) and WORKER_VALIDATOR.is_valid(candidate) and candidate['output']['order_id']=='ORD-1001'
        outcomes.append(candidate if instruction['operation']=='return' and valid else {
            'worker_id':worker_id,'status':'FAILED','output':None,
            'failure_code':'WORKER_EXECUTION_FAILED' if instruction['operation']=='raise' else 'INVALID_WORKER_OUTPUT'})
    success=[o for o in outcomes if o['status']=='SUCCEEDED']
    brief=None if not success else {'order_id':'ORD-1001','sections':[{'worker_id':o['worker_id'],'output':o['output']} for o in success],
                                  'missing_workers':[o['worker_id'] for o in outcomes if o['status']=='FAILED'],'complete':len(success)==3}
    return {'worker_outcomes':outcomes,'status':'SUCCEEDED' if len(success)==3 else 'PARTIAL' if success else 'FAILED',
            'synthesis_invoked':bool(success),'brief':brief,'failure_code':None if success else 'ALL_WORKERS_FAILED'}

def assert_case_behavior(result,events,case,trace_path,source):
    require(finite_json(result) and RESULT_VALIDATOR.is_valid(result),'Invalid run result schema')
    expected=expected_case(case);mode=case['execution_mode'];limit=1 if mode=='sequential' else 2
    require(result['case_id']==case['case_id'] and result['execution_mode']==mode,'Wrong requested case/mode')
    require(result['order_id']=='ORD-1001' and result['trace_path']==trace_path and result['concurrency_limit']==limit,'Wrong run binding')
    for key,value in expected.items():require(result[key]==value,f'Wrong result {key}')
    require(len(events)==(11 if expected['synthesis_invoked'] else 9),'Wrong event count')
    event_ids=set()
    for sequence,event in enumerate(events,1):
        require(finite_json(event) and EVENT_VALIDATOR.is_valid(event),'Invalid event schema')
        require(event['sequence']==sequence and event['run_id']==result['run_id'] and event['source']==source,'Wrong event identity or sequence')
        require(event['event_id'] not in event_ids,'Duplicate event ID');event_ids.add(event['event_id'])
    context={'scenario_id':'order-brief','case_id':case['case_id'],'execution_mode':mode,'order_id':'ORD-1001','concurrency_limit':limit}
    require(events[0]['type']=='run.created' and events[0]['data']==context,'Wrong creation context')
    require(events[1]['type']=='run.started' and events[1]['data']==context,'Wrong start context')
    active=set();started=[];completed=[];peak=0;synthesis=[]
    for event in events[2:-1]:
        data=event['data'];name=data.get('step_name');kind=event['type']
        if name=='synthesize':
            require(len(completed)==3 and not active and expected['synthesis_invoked'],'Early or forbidden synthesis')
            if not synthesis:require(kind=='step.started' and data=={'step_name':'synthesize','worker_outcomes':expected['worker_outcomes']},'Wrong synthesis input')
            else:require(synthesis==['step.started'] and kind=='step.completed' and data=={'step_name':'synthesize','brief':expected['brief']},'Wrong synthesis completion')
            synthesis.append(kind);continue
        require(not synthesis and name in ['worker.'+i for i in WORKER_IDS],'Unexpected step')
        worker_id=name[len('worker.'):]
        if kind=='step.started':
            require(worker_id not in started and worker_id==WORKER_IDS[len(started)],'Duplicate or noncanonical admission')
            require(data=={'step_name':name,'worker_id':worker_id,'order_id':'ORD-1001'},'Wrong worker start')
            started.append(worker_id);active.add(worker_id);peak=max(peak,len(active));require(len(active)<=limit,'Slot bound exceeded')
        else:
            require(worker_id in active and worker_id not in completed,'Terminal without unique start')
            outcome=expected['worker_outcomes'][WORKER_IDS.index(worker_id)]
            require(kind==('step.completed' if outcome['status']=='SUCCEEDED' else 'step.failed') and data=={'step_name':name,'outcome':outcome},'Wrong worker terminal')
            active.remove(worker_id);completed.append(worker_id)
    require(started==list(WORKER_IDS) and completed==list(case['completion_order']) and not active,'Incomplete or wrong completion trajectory')
    require(peak==limit==result['peak_concurrency'],'False observed peak')
    require(synthesis==(['step.started','step.completed'] if expected['synthesis_invoked'] else []),'Wrong synthesis lifecycle')
    require(events[-1]['type']==('run.completed' if expected['synthesis_invoked'] else 'run.failed'),'Wrong terminal type')
    require(events[-1]['data']=={k:result[k] for k in TERMINAL_KEYS},'Terminal/result mismatch')

def semantic_trace(result,events,case,trace_path,source):
    assert_case_behavior(result,events,case,trace_path,source)
    projection={'run':[],'workers':{i:[] for i in WORKER_IDS},'synthesis':[],'completion_order':[]}
    for event in events:
        normalized=deepcopy(normalize_event(event));name=event['data'].get('step_name','')
        if name.startswith('worker.'):
            worker_id=name[len('worker.'):];normalized.pop('sequence')
            projection['workers'][worker_id].append(normalized)
            if event['type']!='step.started':projection['completion_order'].append(worker_id)
        elif name=='synthesize':projection['synthesis'].append(normalized)
        else:projection['run'].append(normalized)
    return projection

def business_projection(result):
    return {key:deepcopy(result[key]) for key in ('order_id','status','failure_code','worker_outcomes','synthesis_invoked','brief')}

def validate_probe_reports(ts_report,python_report):
    try:
        assertions=[(suite,a) for suite in ts_report['testResults'] for a in suite['assertionResults']]
        if ts_report['success'] is not True or ts_report['numFailedTests']!=0 or ts_report['numFailedTestSuites']!=0 or ts_report['numPassedTests']<=0 or ts_report['numTotalTests']!=len(assertions):raise ValueError('Failed/empty TS suite')
        passed={a['title'] for suite,a in assertions if suite['name'].replace('\\','/').endswith('/executor.test.ts') and suite['status']=='passed' and a['status']=='passed' and a['fullName'].split()[-1]==a['title']}
        if not set(REQUIRED_PROBES)<=passed:raise ValueError('Required TS probes not passed')
        required={f'test_executor.ExecutorTests.test_{name}' for name in REQUIRED_PROBES}
        p=python_report
        if p['successful'] is not True or p['tests_run']<=0 or p['failed'] or p['skipped'] or len(p['discovered'])!=p['tests_run'] or set(p['discovered'])!=set(p['passed']) or not required<=set(p['passed']):raise ValueError('Required Python probes not passed')
        return {'typescript':{'tests':ts_report['numPassedTests'],'passed_probes':list(REQUIRED_PROBES)},'python':{'tests':p['tests_run'],'passed_probes':sorted(required)}}
    except (KeyError,TypeError,IndexError) as error:raise ValueError('Malformed test proof') from error

def run_cli(command,env=None):
    process=subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,text=True,capture_output=True,check=True)
    lines=[line for line in process.stdout.splitlines() if line.strip()]
    require(len(lines)==1,'CLI must emit one nonblank JSON line')
    def reject(value):raise ValueError('Nonstandard JSON constant: '+value)
    result=json.loads(lines[0],parse_constant=reject);require(type(result) is dict,'CLI result must be object');return result

def verify_cases():
    env=os.environ.copy();env['PYTHONPATH']=str(PY_SRC);records=[]
    for spec in load_scenario().cases:
        case=asdict(spec);traces={lang:str((OUTPUT_ROOT/'traces'/f'{spec.case_id}.{lang}.jsonl').resolve()) for lang in ('typescript','python')}
        options=['--mode',spec.execution_mode,'--case',spec.case_id,'--trace']
        ts=run_cli(['npm','--silent','--prefix',str(TS_ROOT),'run','run','--',*options,traces['typescript']])
        py=run_cli([sys.executable,'-m','boundrelay_m3',*options,traces['python']],env)
        ts_semantic=semantic_trace(ts,read_jsonl(traces['typescript']),case,traces['typescript'],'typescript')
        py_semantic=semantic_trace(py,read_jsonl(traces['python']),case,traces['python'],'python')
        require(normalize_result(ts)==normalize_result(py),f'Result parity: {spec.case_id}')
        require(ts_semantic==py_semantic,f'Semantic trace parity: {spec.case_id}')
        records.append({**normalize_result(ts),'typescript_trace':traces['typescript'],'python_trace':traces['python']})
    require(len(records)==6,'Expected six cases')
    for record in records[1:3]:require(business_projection(record)==business_projection(records[0]),'Cross-mode business mismatch')
    return records
