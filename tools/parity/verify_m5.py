from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .normalize import normalize_event,normalize_result,read_jsonl
from .verify_m2 import assert_clean_worktree,_revision
from . import verify_m3 as m3gate
from .verify_m3 import business_projection,expected_case

ROOT=Path(__file__).resolve().parents[2]
PY_SRC=ROOT/'lessons/05-side-effects-approval/python/src'
TS_ROOT=ROOT/'lessons/05-side-effects-approval/typescript'
OUTPUT_ROOT=ROOT/'.boundrelay/m5'
EVIDENCE_PATH=OUTPUT_ROOT/'verification-evidence.json'
sys.path.insert(0,str(PY_SRC))
from boundrelay_m5.schemas import (EVENT_VALIDATOR,RESULT_VALIDATOR,finite_json,
    validate_run_state_document,canonical_state_body,state_digest,validate_effect_record,validate_audit_record)
from boundrelay_m5.scenario import load_scenario
from boundrelay_m5.state_store import load_run_state,load_run_state_document
from boundrelay_m5.types import WORKER_IDS,StateBinding

EXECUTOR_PROBES=('no_submission_without_granted_approval','submit_marker_precedes_ledger_submit_and_outcome_recorded_after',
                 'reads_bounded_and_effect_submitted_once','declared_read_failures_stop_before_approval',
                 'store_is_optional_plain_m4_reads_when_absent','crash_before_submit_fires_before_the_marker')
RECOVERY_PROBES=('resume_proves_landed_effect_by_key_lookup','resume_resubmits_absent_effect_under_same_key',
                 'unprovable_effect_stays_unknown','duplicate_key_adopts_recorded_outcome','terminal_states_not_resumable',
                 'binding_mismatch_rejected','runtime_never_reads_audit')
REQUIRED_PROBES=EXECUTOR_PROBES+RECOVERY_PROBES
PAYLOAD={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
DIGEST=hashlib.sha256(json.dumps(PAYLOAD,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
KEY='cancel-and-refund:ORD-1001'
OUTCOME={'refund_id':'RFL-1001','refunded_at':'2026-11-02T00:00:00Z'}
LEDGER_RECORD={'key':KEY,'payload_digest':DIGEST,'effect':{'status':'EFFECT_COMPLETED','outcome':OUTCOME}}
TERMINAL_KEYS=('status','worker_outcomes','synthesis_invoked','brief','failure_code','peak_concurrency',
               'reconciled','approval_decision','effect_status','idempotency_key')
APPROVAL_KEYS={'operation','order_id','payload_digest'}
CHECKPOINT_SAVED_KEYS={'case_id','execution_mode','requested_order_id','concurrency_limit','step_name','state_status','sequence_cursor'}

def require(condition,message):
    if not condition:raise AssertionError(message)

def clear_previous_evidence():
    target=OUTPUT_ROOT.absolute()
    if target.name!='m5' or target.resolve()!=target or target in (ROOT.resolve(),ROOT.parent.resolve()):
        raise RuntimeError('Unsafe evidence root')
    if target.exists():
        if not target.is_dir():raise RuntimeError('Unsafe evidence root')
        shutil.rmtree(target)

def validate_lower_evidence(revision):
    for milestone in ('m0','m1','m2','m3','m4'):
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

def read_ledger(state_dir):
    path=Path(state_dir)/'effect-ledger.json'
    if not path.exists():return []
    records=json.loads(path.read_text(encoding='utf-8'))['records']
    for record in records:
        if not validate_effect_record(record).valid:raise AssertionError('Invalid ledger record')
    return records

def read_audit(state_dir):
    path=Path(state_dir)/'audit.jsonl'
    if not path.exists():return []
    records=[json.loads(line) for line in path.read_text(encoding='utf-8').split('\n') if line.strip()]
    for record in records:
        if not validate_audit_record(record):raise AssertionError('Invalid audit record')
    return records

def normalize_state(document):
    require(type(document) is dict,'State document must be an object')
    require(validate_run_state_document(document).valid,'Invalid state document schema')
    require(state_digest(canonical_state_body(document))==document['digest'],'State document digest mismatch')
    return {key:deepcopy(value) for key,value in document.items() if key not in ('run_id','digest')}

CRASH_BEFORE='before_submit';CRASH_WINDOW='in_submit_window'
def _expect(kind,crash,**fields):
    base={'kind':kind,'crash':crash,'terminal':None,'status':None,'decision':None,'effect_status':None,'reconciled':False,
          'failure_code':None,'tool':False,'dup':None,'state_status':'RUNNING','marker':False,'effect':False,'effect_dup':None,
          'ledger':0,'audit':(),'reads':kind!='resume','peak':1 if kind=='resume' else 2,'resumed':kind=='resume'}
    base.update(fields);return base
PHASE_EXPECTATIONS={'approval-granted-effect-once':(_expect('fresh',None,terminal='run.completed',status='SUCCEEDED',decision='granted',
    effect_status='EFFECT_COMPLETED',tool=True,dup=False,state_status='SUCCEEDED',marker=True,effect=True,effect_dup=False,ledger=1,audit=('approval','effect')),),
    'approval-rejected-no-effect':(_expect('fresh',None,terminal='run.failed',status='FAILED',decision='rejected',failure_code='APPROVAL_REJECTED',
    state_status='FAILED',ledger=0,audit=('approval',)),),
    'retry-before-submit':(_expect('fresh',CRASH_BEFORE,decision='granted',audit=('approval',),peak=2),
                           _expect('resume',None,terminal='run.completed',status='SUCCEEDED',decision='granted',effect_status='EFFECT_COMPLETED',
    tool=True,dup=False,state_status='SUCCEEDED',marker=True,effect=True,effect_dup=False,ledger=1,audit=('approval','effect'))),
    'crash-submit-window-resolved':(_expect('fresh',CRASH_WINDOW,decision='granted',tool=True,marker=True,ledger=1,audit=('approval',),peak=2),
                                    _expect('resume',None,terminal='run.completed',status='SUCCEEDED',decision='granted',effect_status='EFFECT_COMPLETED',
    reconciled=True,state_status='SUCCEEDED',marker=True,effect=True,effect_dup=False,ledger=1,audit=('effect',))),
    'sink-unavailable-unknown':(_expect('fresh',CRASH_WINDOW,decision='granted',tool=True,marker=True,ledger=1,audit=('approval',),peak=2),
                                _expect('resume',None,terminal='run.completed',status='UNKNOWN',decision='granted',effect_status='EFFECT_UNPROVABLE',
    state_status='UNKNOWN',marker=True,ledger=1,audit=())),
    'duplicate-key-suppressed':(_expect('fresh',None,terminal='run.completed',status='SUCCEEDED',decision='granted',effect_status='EFFECT_COMPLETED',
    tool=True,dup=False,state_status='SUCCEEDED',marker=True,effect=True,effect_dup=False,ledger=1,audit=('approval','effect')),
                                _expect('duplicate',None,terminal='run.completed',status='SUCCEEDED',decision='granted',effect_status='EFFECT_COMPLETED',
    tool=True,dup=True,state_status='SUCCEEDED',marker=True,effect=True,effect_dup=True,ledger=1,audit=('approval','effect')))}

def _binding(case):
    return StateBinding(case_id=case['case_id'],execution_mode=case['execution_mode'],requested_order_id='ORD-1001',
                        concurrency_limit=1 if case['execution_mode']=='sequential' else 2)

def _recorded(document):
    return {step['worker_id']:{'worker_id':step['worker_id'],'status':step['status'],'output':step['output'],'failure_code':step['failure_code']}
            for step in document['steps'] if step['status'] in ('SUCCEEDED','FAILED')}

def _validate_phase_events(phase,case,source,run_id,context,limit,expect,outcomes):
    events=phase['events']
    require(len(events)>0,'Missing phase trace')
    ids=set();started=[];completed=[];active=[];peak=0;checkpoints=0
    requested=0;granted=0;rejected=0;tool_req=0;tool_done=0;terminals=[]
    for position,event in enumerate(events):
        require(finite_json(event) and EVENT_VALIDATOR.is_valid(event),'Invalid event schema')
        require(event['sequence']==position+1,'Noncontiguous event sequence')
        require(event['run_id']==run_id and event['source']==source,'Wrong event identity')
        require(event['event_id'] not in ids,'Duplicate event ID');ids.add(event['event_id'])
        type_=event['type'];data=event['data'];name=data.get('step_name')
        if position==0:
            require(type_=='run.created' and data==context,'Wrong creation context');continue
        if position==1:
            require(type_=='run.started' and data==context,'Wrong start context');continue
        if type_=='checkpoint.saved':
            require(set(data)==CHECKPOINT_SAVED_KEYS,'Wrong checkpoint payload keys')
            require(len(completed)>checkpoints and data['step_name']==completed[-1],'Checkpoint must follow its own terminal')
            require(data['state_status']=='RUNNING' and data['sequence_cursor']==len(completed),'Wrong checkpoint cursor/status')
            require(data['case_id']==case['case_id'] and data['requested_order_id']=='ORD-1001' and data['execution_mode']==case['execution_mode'] and data['concurrency_limit']==limit,'Wrong checkpoint binding')
            checkpoints+=1;continue
        if type_ in ('approval.requested','approval.granted','approval.rejected'):
            require(set(data)==APPROVAL_KEYS,'Wrong approval payload keys')
            require(data['operation']=='cancel-and-refund' and data['order_id']=='ORD-1001' and data['payload_digest']==DIGEST,'Wrong approval digest binding')
            if type_=='approval.requested':
                require(granted+rejected==0 and tool_req==0,'Approval decision before request');requested+=1
            elif type_=='approval.granted':
                require(requested==1 and granted+rejected==0,'Decision without single request');granted=1
            else:
                require(requested==1 and granted+rejected==0,'Decision without single request');rejected=1
            continue
        if type_=='tool.requested':
            require(set(data)=={'key','payload_digest','side_effect_class'} and data['key']==KEY and data['payload_digest']==DIGEST and data['side_effect_class']=='external','Wrong tool request payload')
            require(granted==1 and tool_req==0,'Submission without granted approval event order');tool_req=1;continue
        if type_=='tool.completed':
            require(set(data)=={'key','status','duplicate'} and data['key']==KEY and data['status']=='EFFECT_COMPLETED' and data['duplicate']==expect['dup'],'Wrong tool completion payload')
            require(tool_req==1 and tool_done==0,'Completion without request');tool_done=1;continue
        if type_=='tool.failed':require(False,'Unexpected tool failure')
        if type_ in ('run.completed','run.failed'):
            require(not terminals,'Duplicate terminal event');terminals.append(type_);continue
        require(name is not None and name.startswith('worker.'),'Unexpected event')
        worker_id=name[7:]
        if type_=='step.started':
            require(worker_id not in started and worker_id==WORKER_IDS[len(started)],'Duplicate or noncanonical admission')
            require(set(data)=={'step_name','worker_id','order_id'} and data['worker_id']==worker_id and data['order_id']=='ORD-1001','Wrong worker start payload')
            started.append(worker_id);active.append(worker_id);peak=max(peak,len(active));require(len(active)<=limit,'Slot bound exceeded')
        else:
            require(type_ in ('step.completed','step.failed') and worker_id in active and worker_id not in completed,'Terminal without unique start')
            require(set(data)=={'step_name','outcome'} and data['outcome']==outcomes[worker_id],'Wrong worker terminal payload')
            require(type_==('step.completed' if outcomes[worker_id]['status']=='SUCCEEDED' else 'step.failed'),'Wrong terminal kind')
            active.remove(worker_id);completed.append(worker_id)

    expected_started=list(WORKER_IDS) if expect['reads'] else []
    require(started==expected_started and completed==expected_started,'Wrong read trajectory')
    require(not active,'Workers still active at phase end')
    require(checkpoints==len(expected_started),'Wrong checkpoint count')
    require(bool(requested)==('approval' in expect['audit'] or (expect['tool'] and expect['kind']!='resume')),'Wrong approval presence')
    require(granted+rejected==(1 if requested else 0),'Approval without decision')
    require(bool(granted)==('approval' in expect['audit'] and expect['decision']=='granted'),'Wrong approval decision')
    require(bool(rejected)==('approval' in expect['audit'] and expect['decision']=='rejected'),'Unexpected approval rejection event')
    require(tool_req==(1 if expect['tool'] else 0),'Wrong tool.requested count')
    require(tool_done==(1 if expect['tool'] and not expect['crash'] else 0),'Wrong tool.completed count')
    if expect['crash']==CRASH_BEFORE:require(not tool_req,'Crash before submit must not submit')
    if expect['crash']==CRASH_WINDOW:require(tool_req==1 and not tool_done,'Crash window must stop between submit and confirm')
    if expect['crash'] is not None:require(not terminals,'Crash phase must not emit a terminal event')
    else:
        require(terminals==[expect['terminal']] and events[-1]['type']==expect['terminal'],'Wrong or missing terminal event')
        require(set(events[-1]['data'])==set(TERMINAL_KEYS),'Wrong terminal payload keys')
        require(events[-1]['data']=={key:phase['result'][key] for key in TERMINAL_KEYS},'Terminal/result mismatch')
    return peak

def _validate_result(phase,expect,limit,observed_peak,case):
    result=phase['result'];require(type(result) is dict,'Missing phase result')
    require(finite_json(result) and RESULT_VALIDATOR.is_valid(result),'Invalid run result schema')
    require(result['case_id']==case['case_id'] and result['execution_mode']==case['execution_mode'] and result['order_id']=='ORD-1001','Wrong result binding')
    require(result['trace_path']==phase['trace_path'] and result['state_dir']==phase['state_dir'] and result['concurrency_limit']==limit,'Wrong result trace binding')
    require(result['peak_concurrency']==max(observed_peak,1),'False observed peak')
    expected=m3gate.expected_case(case)
    require(result['worker_outcomes']==expected['worker_outcomes'] and result['synthesis_invoked'] is False and result['brief'] is None,'Wrong worker outcomes')
    for key,field in (('status','status'),('failure_code','failure_code'),('approval_decision','decision'),('effect_status','effect_status'),('reconciled','reconciled')):
        require(result[key]==expect[field],f'Wrong result {key}')
    require(result['run_state_status']==expect['state_status'],'Result run-state status must match the state document')
    if expect['resumed']:
        require(result['resumed'] is True and result['restored_cursor']==3 and list(result['restored_worker_ids'])==list(WORKER_IDS),'Wrong restore fields')
    else:
        require(result['resumed'] is False and result['restored_cursor'] is None and result['restored_worker_ids']==[],'Fresh result must not claim restore')
    keyed=expect['effect_status'] is not None
    require(result['idempotency_key']==(KEY if keyed else None),'Wrong idempotency key')

def assert_flow_behavior(flow,source):
    case=flow['case'];binding=_binding(case);limit=binding.concurrency_limit
    require(flow['case_id']==case['case_id'],'Wrong flow case')
    expectations=PHASE_EXPECTATIONS[case['case_id']]
    require(len(flow['phases'])==len(expectations),'Wrong phase count')
    outcomes={outcome['worker_id']:outcome for outcome in expected_case(case)['worker_outcomes']}
    run_id=None;previous_ledger=[];previous_audit=[]
    for phase,expect in zip(flow['phases'],expectations):
        if expect['crash'] is not None:
            require(phase['exit_code']==2 and phase['result'] is None,'Crash phase must exit 2 without a result')
        else:
            require(phase['exit_code']==0 and phase['result'] is not None,'Domain phase must exit 0 with a result')
        phase_run_id=phase['result']['run_id'] if phase['result'] is not None else (phase['state']['run_id'] if phase.get('state') is not None else None)
        require(phase_run_id is not None,'Phase lacks a run identity')
        if expect['kind']=='resume':require(phase_run_id==run_id,'Resume must continue the same run identity')
        elif run_id is not None:require(phase_run_id!=run_id,'Fresh or duplicate run must use a new run identity')
        context={'scenario_id':'order-closure','case_id':case['case_id'],'execution_mode':case['execution_mode'],'order_id':'ORD-1001','concurrency_limit':limit,'state_dir':phase['state_dir']}
        observed_peak=_validate_phase_events(phase,case,source,phase_run_id,context,limit,expect,outcomes)
        if phase['result'] is not None:_validate_result(phase,expect,limit,observed_peak,case)
        _validate_phase_state(phase,expect,case,limit,outcomes)
        ledger=phase['ledger'];audit=phase['audit']
        require(ledger[:len(previous_ledger)]==previous_ledger,'Ledger history changed between phases')
        require(audit[:len(previous_audit)]==previous_audit,'Audit history was reordered or rewritten')
        _validate_audit_delta(audit[len(previous_audit):],expect,case)
        require(len(ledger)==expect['ledger'],'Wrong ledger record count')
        if ledger:require(ledger==[LEDGER_RECORD],'Wrong ledger record contents')
        previous_ledger=list(ledger);previous_audit=list(audit);run_id=phase_run_id
    require(len(previous_ledger)<=1,'Effect-once violated: more than one ledger record')

def _validate_phase_state(phase,expect,case,limit,outcomes):
    state=phase.get('state')
    require(state is not None,'Missing phase state document')
    require(validate_run_state_document(state).valid and state_digest(canonical_state_body(state))==state['digest'],'Invalid state document')
    require((state['case_id'],state['execution_mode'],state['requested_order_id'],state['concurrency_limit'])==(case['case_id'],case['execution_mode'],'ORD-1001',limit),'Wrong state binding')
    require(_recorded(state)==outcomes,'State outcomes diverge from the fixture')
    require(state['sequence_cursor']==3,'State cursor mismatch')
    require(state['status']==expect['state_status'],'Wrong state status')
    if phase['result'] is not None:require(state['status']==phase['result']['run_state_status'],'State status must mirror the result')
    marker=state['submit_marker']
    require((marker is not None)==expect['marker'],'Submit-marker presence does not match the phase kind')
    if marker is not None:require(marker=={'key':KEY,'payload_digest':DIGEST},'Wrong submit-marker binding')
    effect=state['effect']
    require((effect is not None)==expect['effect'],'Effect presence does not match the phase kind')
    if effect is not None:require(effect=={'key':KEY,'payload_digest':DIGEST,'status':'EFFECT_COMPLETED','outcome':OUTCOME,'duplicate':expect['effect_dup']},'Wrong recorded effect')

def _validate_audit_delta(delta,expect,case):
    require([record['kind'] for record in delta]==list(expect['audit']),'Wrong audit delta for phase')
    for record in delta:
        if record['kind']=='approval':
            require(record=={'kind':'approval','operation':'cancel-and-refund','order_id':'ORD-1001','payload_digest':DIGEST,'decision':expect['decision'],'approver':case['approval']['approver']},'Wrong approval audit record')
        else:
            require(record=={'kind':'effect','operation':'cancel-and-refund','order_id':'ORD-1001','idempotency_key':KEY,'effect_status':'EFFECT_COMPLETED','duplicate':expect['effect_dup']},'Wrong effect audit record')

def semantic_flow(flow,source):
    assert_flow_behavior(flow,source)
    workers={worker_id:[] for worker_id in WORKER_IDS};phases=[]
    for phase in flow['phases']:
        entry={'kind':phase['kind'],'run':[],'checkpoints':[],'completion_order':[]}
        for event in phase['events']:
            normalized=deepcopy(normalize_event(event));name=event['data'].get('step_name','')
            if name.startswith('worker.'):
                worker_id=name[7:];normalized.pop('sequence');workers[worker_id].append(normalized)
                if event['type']!='step.started':entry['completion_order'].append(worker_id)
            elif event['type']=='checkpoint.saved':entry['checkpoints'].append(normalized)
            else:
                if isinstance(normalized.get('data'),dict):normalized['data'].pop('state_dir',None)
                entry['run'].append(normalized)
        phases.append({'kind':entry['kind'],'run':entry['run'],'checkpoints':entry['checkpoints'],
                       'completion_order':entry['completion_order'],'ledger':deepcopy(phase['ledger']),'audit':deepcopy(phase['audit'])})
    final=[phase for phase in flow['phases'] if phase.get('state') is not None][-1]
    return {'workers':workers,'phases':phases,'state':normalize_state(final['state'])}

def validate_probe_reports(ts_report,python_report):
    try:
        assertions=[(suite,a) for suite in ts_report['testResults'] for a in suite['assertionResults']]
        if ts_report['success'] is not True or ts_report['numFailedTests']!=0 or ts_report['numFailedTestSuites']!=0 or ts_report['numPassedTests']<=0 or ts_report['numTotalTests']!=len(assertions):raise ValueError('Failed/empty TS suite')
        def passed(suffix):
            return {a['title'] for suite,a in assertions if suite['name'].replace('\\','/').endswith(suffix) and suite['status']=='passed' and a['status']=='passed' and a['fullName'].split()[-1]==a['title']}
        if not set(EXECUTOR_PROBES)<=passed('/executor.test.ts'):raise ValueError('Required TS executor probes not passed')
        if not set(RECOVERY_PROBES)<=passed('/recovery.test.ts'):raise ValueError('Required TS recovery probes not passed')
        required={f'test_executor.ExecutorTests.test_{name}' for name in EXECUTOR_PROBES}|{f'test_recovery.RecoveryTests.test_{name}' for name in RECOVERY_PROBES}
        report=python_report
        if report['successful'] is not True or report['tests_run']<=0 or report['failed'] or report['skipped'] or len(report['discovered'])!=report['tests_run'] or set(report['discovered'])!=set(report['passed']) or not required<=set(report['passed']):raise ValueError('Required Python probes not passed')
        if any('_FailedTest' in name for name in report['discovered']):raise ValueError('Failed Python discovery')
        return {'typescript':{'tests':ts_report['numPassedTests'],'passed_probes':list(EXECUTOR_PROBES+RECOVERY_PROBES)},
                'python':{'tests':report['tests_run'],'passed_probes':sorted(required)}}
    except (KeyError,TypeError,IndexError) as error:raise ValueError('Malformed test proof') from error

CASE_PHASES={'approval-granted-effect-once':(('fresh',None),),
             'approval-rejected-no-effect':(('fresh',None),),
             'retry-before-submit':(('fresh','before_submit'),('resume',None)),
             'crash-submit-window-resolved':(('fresh','in_submit_window'),('resume',None)),
             'sink-unavailable-unknown':(('fresh','in_submit_window'),('resume',None)),
             'duplicate-key-suppressed':(('fresh',None),('duplicate',None))}

def _normalize_result(result):
    normalized=normalize_result(result);normalized.pop('state_dir',None);return normalized

def _spawn(command,env=None):
    process=subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,text=True,capture_output=True)
    return process.returncode,process.stdout,process.stderr

def _cli_result(code,stdout):
    require(code==0,'CLI must exit 0 for a domain phase')
    lines=[line for line in stdout.splitlines() if line.strip()]
    require(len(lines)==1,'CLI must emit one nonblank JSON line')
    def reject(value):raise ValueError('Nonstandard JSON constant: '+value)
    result=json.loads(lines[0],parse_constant=reject);require(type(result) is dict,'CLI result must be an object');return result

def _cli_failure(code,stdout):
    require(code==2,'Tooling or crash phase must exit 2')
    require(not [line for line in stdout.splitlines() if line.strip()],'Crash phase must not print a result line')

def _run_flow(case,language,env,trace_dir):
    case_id=case['case_id']
    def command(options):
        if language=='typescript':return ['npm','--silent','--prefix',str(TS_ROOT),'run','run','--',*options]
        return [sys.executable,'-m','boundrelay_m5',*options]
    binding=_binding(case)
    with tempfile.TemporaryDirectory() as tmp:
        state_dir=str(Path(tmp)/'state');phases=[]
        for kind,crash_control in CASE_PHASES[case_id]:
            trace=str((Path(trace_dir)/f'{case_id}.{language}.{kind}.jsonl').resolve())
            options=['--case',case_id,'--trace',trace,'--state-dir',state_dir]
            if kind=='resume':options.append('--resume')
            code,stdout,_=_spawn(command(options),env)
            if crash_control is not None:
                _cli_failure(code,stdout)
                document=load_run_state(state_dir,binding)['document']
                phases.append({'kind':kind,'crash':crash_control,'exit_code':code,'result':None,'events':read_jsonl(trace),
                               'trace_path':trace,'state_dir':state_dir,'state':document,
                               'ledger':read_ledger(state_dir),'audit':read_audit(state_dir)});continue
            result=_cli_result(code,stdout);run_id=result['run_id']
            document=load_run_state_document(Path(state_dir)/run_id/'state.json',binding)
            phases.append({'kind':kind,'crash':None,'exit_code':code,'result':result,'events':read_jsonl(trace),
                           'trace_path':trace,'state_dir':state_dir,'state':document,
                           'ledger':read_ledger(state_dir),'audit':read_audit(state_dir)})
        return {'case_id':case_id,'case':case,'phases':phases}

def verify_cases():
    env=os.environ.copy();env['PYTHONPATH']=str(PY_SRC)
    trace_dir=OUTPUT_ROOT/'traces';trace_dir.mkdir(parents=True,exist_ok=True)
    records=[];flows={}
    for spec in load_scenario().cases:
        case=asdict(spec)
        per_language={language:_run_flow(case,language,env,trace_dir) for language in ('typescript','python')}
        for language,flow in per_language.items():assert_flow_behavior(flow,language)
        ts_flow=per_language['typescript'];py_flow=per_language['python']
        for index,(ts_phase,py_phase) in enumerate(zip(ts_flow['phases'],py_flow['phases'])):
            if ts_phase['result'] is not None:
                require(_normalize_result(ts_phase['result'])==_normalize_result(py_phase['result']),f"Result parity phase {index}: {case['case_id']}")
        require(semantic_flow(ts_flow,'typescript')==semantic_flow(py_flow,'python'),f"Semantic trace parity: {case['case_id']}")
        flows[case['case_id']]=ts_flow
        records.append({'case_id':case['case_id'],'phases':[{'kind':phase['kind'],'exit_code':phase['exit_code'],
                       'result':_normalize_result(phase['result']) if phase['result'] is not None else None,
                       'trace_path':phase['trace_path'],'state':normalize_state(phase['state']) if phase.get('state') is not None else None,
                       'ledger':phase['ledger'],'audit':phase['audit']} for phase in ts_flow['phases']]})
    require(len(records)==6,'Expected six case records')
    def phase_result(case_id,index):return flows[case_id]['phases'][index]['result']
    projection=business_projection(phase_result('approval-granted-effect-once',0))
    for case_id,index in (('retry-before-submit',1),('crash-submit-window-resolved',1)):
        require(business_projection(phase_result(case_id,index))==projection,f'Business projection mismatch: {case_id}')
        for key in ('approval_decision','effect_status','idempotency_key'):
            require(phase_result(case_id,index)[key]==phase_result('approval-granted-effect-once',0)[key],f'Business projection mismatch (effect fields): {case_id}')
    rejected=phase_result('approval-rejected-no-effect',0)
    require(rejected['status']=='FAILED' and rejected['failure_code']=='APPROVAL_REJECTED' and not flows['approval-rejected-no-effect']['phases'][0]['ledger'],'Rejection must stay FAILED/APPROVAL_REJECTED with an empty ledger')
    unknown=phase_result('sink-unavailable-unknown',1)
    require(unknown['status']=='UNKNOWN' and unknown['run_state_status']=='UNKNOWN' and unknown['reconciled'] is False,'UNKNOWN must stay unflattened')
    duplicate=phase_result('duplicate-key-suppressed',1)
    require(duplicate['status']=='SUCCEEDED' and duplicate['reconciled'] is False and len(flows['duplicate-key-suppressed']['phases'][1]['ledger'])==1,'Duplicate run must adopt the recorded outcome with one ledger record')
    return records
