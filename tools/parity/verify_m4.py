from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from .normalize import normalize_event,normalize_result,read_jsonl
from .verify_m2 import assert_clean_worktree,_revision
from . import verify_m3 as m3gate
from .verify_m3 import business_projection,expected_case

ROOT=Path(__file__).resolve().parents[2]
PY_SRC=ROOT/'lessons/04-durable-state-recovery/python/src'
TS_ROOT=ROOT/'lessons/04-durable-state-recovery/typescript'
OUTPUT_ROOT=ROOT/'.boundrelay/m4'
EVIDENCE_PATH=OUTPUT_ROOT/'verification-evidence.json'
sys.path.insert(0,str(PY_SRC))
from boundrelay_m4.types import WORKER_IDS,StateBinding
from boundrelay_m4.schemas import EVENT_VALIDATOR,RESULT_VALIDATOR,finite_json,validate_run_state_document,canonical_state_body,state_digest
from boundrelay_m4.scenario import load_scenario
from boundrelay_m4.state_store import load_run_state,load_run_state_document

EXECUTOR_PROBES=('parallel_calls_overlap_without_exceeding_two','sequential_never_overlaps',
                 'declared_failures_do_not_retry','unexpected_error_drains_without_admitting_queued_worker',
                 'cancel_before_stops_admission_and_records_drained_terminals','crash_after_requires_quiescent_boundary',
                 'crash_after_fires_after_recorded_failure')
RECOVERY_PROBES=('resume_skips_recorded_workers_and_reexecutes_inflight_exactly_once','resume_never_reexecutes_recorded_failures',
                 'replay_seeds_new_run_without_touching_source','cancel_resume_completes_remaining_workers_only',
                 'resume_rejects_binding_mismatch_and_terminal_states_without_invocations')
REQUIRED_PROBES=EXECUTOR_PROBES
TERMINAL_KEYS=('status','worker_outcomes','synthesis_invoked','brief','failure_code','peak_concurrency')
CONTEXT_KEYS=('scenario_id','case_id','execution_mode','order_id','concurrency_limit','state_dir')
BINDING_KEYS=('case_id','execution_mode','requested_order_id','concurrency_limit')
WORKER_STARTED_KEYS=('step_name','worker_id','order_id')
WORKER_TERMINAL_KEYS=('step_name','outcome')
SYNTH_STARTED_KEYS=('step_name','worker_outcomes')
SYNTH_COMPLETED_KEYS=('step_name','brief')
CHECKPOINT_SAVED_KEYS=('case_id','execution_mode','requested_order_id','concurrency_limit','step_name','state_status','sequence_cursor')
CHECKPOINT_RESTORED_KEYS=('case_id','execution_mode','requested_order_id','concurrency_limit','state_status','restored_cursor','restored_worker_ids')
CANCELLED_KEYS=('case_id','execution_mode','requested_order_id','concurrency_limit','cancelled_before','code')

def require(condition,message):
    if not condition:raise AssertionError(message)

def clear_previous_evidence():
    target=OUTPUT_ROOT.absolute()
    if target.name!='m4' or target.resolve()!=target or target in (ROOT.resolve(),ROOT.parent.resolve()):
        raise RuntimeError('Unsafe evidence root')
    if target.exists():
        if not target.is_dir():raise RuntimeError('Unsafe evidence root')
        shutil.rmtree(target)

def validate_lower_evidence(revision):
    for milestone in ('m0','m1','m2','m3'):
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

def normalize_state(document):
    require(type(document) is dict,'State document must be an object')
    require(validate_run_state_document(document).valid,'Invalid state document schema')
    require(state_digest(canonical_state_body(document))==document['digest'],'State document digest mismatch')
    return {key:deepcopy(value) for key,value in document.items() if key not in ('run_id','digest')}

def _binding(case):
    return StateBinding(case_id=case['case_id'],execution_mode=case['execution_mode'],requested_order_id='ORD-1001',
                        concurrency_limit=2 if case['execution_mode']=='parallel' else 1)

def _recorded(document):
    return {step['worker_id']:{'worker_id':step['worker_id'],'status':step['status'],'output':step['output'],'failure_code':step['failure_code']}
            for step in document['steps'] if step['status'] in ('SUCCEEDED','FAILED')}

def _phase_shape(case,phase,restored_ids):
    case_id=case['case_id'];completion=list(case['completion_order'])
    if phase['kind']=='fresh':
        if phase.get('crash'):
            started=completion[:2] if case_id=='parallel-crash-resume' else completion
            return started,started[:-1],False,None,None
        if case_id=='parallel-cancel-resume':
            return completion[:2],completion[:2],False,None,'delivery-status'
        return completion,completion,True,'run.completed',None
    pending=[worker_id for worker_id in WORKER_IDS if worker_id not in (restored_ids or [])]
    terminals=[worker_id for worker_id in completion if worker_id in pending]
    return [worker_id for worker_id in WORKER_IDS if worker_id in pending],terminals,True,'run.completed',None

def _validate_phase_events(phase,case,source,run_id,context,limit,restored_ids,restored_status):
    events=phase['events']
    require(len(events)>0,'Missing phase trace')
    expected=m3gate.expected_case(case)
    outcomes={outcome['worker_id']:outcome for outcome in expected['worker_outcomes']}
    expected_started,expected_terminals,expected_synthesis,expected_terminal,expected_cancelled=_phase_shape(case,phase,restored_ids)
    ids=set();started=[];completed=[];active=[];peak=0;synthesis=0;saved=0;unsaved=None
    restored_seen=False;cancelled_seen=False;terminal_seen=False
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
        if type_=='checkpoint.restored':
            require(phase['kind'] in ('resume','replay') and not restored_seen and position==2,'Restore must be the third event of a resuming phase')
            require(set(data)==set(CHECKPOINT_RESTORED_KEYS),'Wrong restore payload keys')
            require(data['state_status']==restored_status and data['restored_cursor']==len(data['restored_worker_ids']),'Wrong restore payload values')
            require(list(data['restored_worker_ids'])==list(WORKER_IDS[:data['restored_cursor']]),'Restore must cover a canonical prefix')
            restored_seen=True;continue
        if restored_ids is not None:require(restored_seen,'Worker event before restore')
        if unsaved is not None:
            require(type_=='checkpoint.saved' and data.get('step_name')==unsaved,'Checkpoint must immediately follow its terminal')
        if type_=='checkpoint.saved':
            require(set(data)==set(CHECKPOINT_SAVED_KEYS),'Wrong checkpoint payload keys')
            require(len(completed)>saved and data['step_name']==completed[-1],'Checkpoint must follow its own terminal')
            require(data['state_status']=='RUNNING' and data['sequence_cursor']==len(restored_ids or [])+len(completed),'Wrong checkpoint cursor/status')
            require(data['case_id']==case['case_id'] and data['requested_order_id']=='ORD-1001' and data['execution_mode']==case['execution_mode'] and data['concurrency_limit']==limit,'Wrong checkpoint binding')
            saved+=1;unsaved=None;continue
        if type_=='run.cancelled':
            require(expected_cancelled is not None and not cancelled_seen and not synthesis and not active,'Unexpected run.cancelled')
            require(set(data)==set(CANCELLED_KEYS) and data['code']=='CANCELLED_BEFORE_STEP' and data['cancelled_before']==expected_cancelled,'Wrong cancel payload')
            require(data['case_id']==case['case_id'] and data['requested_order_id']=='ORD-1001','Wrong cancel binding')
            cancelled_seen=True;continue
        if type_ in ('run.completed','run.failed'):
            require(expected_terminal==type_ and not terminal_seen,'Wrong or duplicate terminal event')
            require(set(data)==set(TERMINAL_KEYS),'Wrong terminal payload keys')
            terminal_seen=True;continue
        if name=='synthesize':
            require((restored_ids is not None or len(completed)==3) and len(completed)==len(expected_terminals) and not active,'Early or forbidden synthesis')
            if synthesis==0:require(type_=='step.started' and set(data)==set(SYNTH_STARTED_KEYS) and list(data['worker_outcomes'])==[outcomes[worker_id] for worker_id in WORKER_IDS],'Wrong synthesis input')
            else:
                require(synthesis==1 and type_=='step.completed' and set(data)==set(SYNTH_COMPLETED_KEYS),'Wrong synthesis completion')
                require(phase['result'] is not None and data['brief']==phase['result']['brief'],'Synthesis brief mismatch')
            synthesis+=1;continue
        require(name is not None and name.startswith('worker.'),'Unexpected event')
        worker_id=name[7:]
        if type_=='step.started':
            require(worker_id not in started and len(started)<len(expected_started) and worker_id==expected_started[len(started)],'Duplicate or noncanonical admission')
            require(set(data)==set(WORKER_STARTED_KEYS) and data['order_id']=='ORD-1001' and data['worker_id']==worker_id,'Wrong worker start payload')
            started.append(worker_id);active.append(worker_id);peak=max(peak,len(active));require(len(active)<=limit,'Slot bound exceeded')
        else:
            require(type_ in ('step.completed','step.failed') and worker_id in active and worker_id not in completed,'Terminal without unique start')
            require(set(data)==set(WORKER_TERMINAL_KEYS) and data['outcome']==outcomes[worker_id],'Wrong worker terminal payload')
            require(type_==('step.completed' if outcomes[worker_id]['status']=='SUCCEEDED' else 'step.failed'),'Wrong terminal kind')
            active.remove(worker_id);completed.append(worker_id);unsaved=worker_id
    require(restored_ids is None or restored_seen,'Missing checkpoint.restored')
    require(started==expected_started,'Wrong admission trajectory')
    require(completed==expected_terminals,'Wrong completion trajectory')
    require(active==([expected_started[-1]] if phase.get('crash') and expected_started else []),'Workers still active at phase end')
    require(saved==len(completed) and unsaved is None,'Write-ahead checkpoint mismatch')
    require(synthesis==(2 if expected_synthesis else 0),'Wrong synthesis lifecycle')
    if expected_cancelled is None:require(not cancelled_seen,'Unexpected run.cancelled')
    else:require(cancelled_seen,'Missing run.cancelled')
    if expected_terminal is None:require(not terminal_seen,'Forbidden terminal event')
    else:
        require(terminal_seen and events[-1]['type']==expected_terminal,'Wrong terminal event')
        require(events[-1]['data']=={key:phase['result'][key] for key in TERMINAL_KEYS},'Terminal/result mismatch')
    return peak

def _validate_result(phase,case,limit,observed_peak,restored_cursor,restored_ids):
    result=phase['result'];require(type(result) is dict,'Missing phase result')
    require(finite_json(result) and RESULT_VALIDATOR.is_valid(result),'Invalid run result schema')
    require(result['case_id']==case['case_id'] and result['execution_mode']==case['execution_mode'] and result['order_id']=='ORD-1001','Wrong result binding')
    require(result['trace_path']==phase['trace_path'] and result['concurrency_limit']==limit,'Wrong result trace binding')
    require(result['peak_concurrency']==max(observed_peak,1),'False observed peak')
    expected=m3gate.expected_case(case)
    if phase['kind']=='fresh' and not phase.get('crash'):
        require(result['resumed'] is False and result['restored_cursor'] is None and result['restored_worker_ids']==[],'Fresh result must not claim restore')
        if case['case_id']=='parallel-cancel-resume':
            require(result['status']=='CANCELLED' and result['run_state_status']=='CANCELLED' and result['failure_code'] is None,'Wrong cancel result')
            require(result['worker_outcomes']==expected['worker_outcomes'][:2] and result['synthesis_invoked'] is False and result['brief'] is None,'Wrong cancel result outcomes')
        else:
            for key in ('status','worker_outcomes','synthesis_invoked','brief','failure_code'):require(result[key]==expected[key],f'Wrong fresh result {key}')
    else:
        require(result['resumed'] is True,'Recovered phase must claim resume')
        require(result['restored_cursor']==restored_cursor and result['restored_worker_ids']==restored_ids,'Wrong restored binding')
        for key in ('status','worker_outcomes','synthesis_invoked','brief','failure_code'):require(result[key]==expected[key],f'Wrong merged result {key}')
        require(result['run_state_status']==result['status'],'Run-state status must mirror the result')

def _assert_merged_identity(flow,case):
    expected=m3gate.expected_case(case)
    expected_outcomes={outcome['worker_id']:{'worker_id':outcome['worker_id'],'status':outcome['status'],'output':outcome['output'],'failure_code':outcome['failure_code']} for outcome in expected['worker_outcomes']}
    recorded={}
    for phase in flow['phases']:
        if phase.get('state') is not None:
            for worker_id,outcome in _recorded(phase['state']).items():
                if worker_id in recorded:require(recorded[worker_id]==outcome,'Re-executed or changed recorded outcome')
                recorded[worker_id]=outcome
        if phase['result'] is not None:
            for outcome in phase['result']['worker_outcomes']:
                worker_id=outcome['worker_id']
                if worker_id in recorded:require(recorded[worker_id]==outcome,'Re-executed or changed recorded outcome')
                recorded[worker_id]=outcome
    require(recorded==expected_outcomes,'Merged outcomes diverge from the fixture expectation')

def _assert_final_state(flow,case):
    final=[phase for phase in flow['phases'] if phase.get('state') is not None][-1]
    document=final['state'];expected=m3gate.expected_case(case)
    if flow['phases'][-1]['result'] is not None:
        require(document['status']==flow['phases'][-1]['result']['run_state_status'],'State status must mirror the result')
    require(_recorded(document)=={worker_id:{'worker_id':worker_id,'status':outcome['status'],'output':outcome['output'],'failure_code':outcome['failure_code']} for worker_id,outcome in ((o['worker_id'],o) for o in expected['worker_outcomes'])},'Final state outcomes diverge from the fixture')
    require(document['sequence_cursor']==3,'Final state cursor mismatch')

def assert_flow_behavior(flow,source):
    case=flow['case'];binding=_binding(case);limit=binding.concurrency_limit
    require(flow['case_id']==case['case_id'],'Wrong flow case')
    run_id=None;recorded={}
    for index,phase in enumerate(flow['phases']):
        kind=phase['kind']
        if kind=='corrupt-resume':
            require(phase['exit_code']==2 and phase['result'] is None and phase['events']==[] and phase['trace_path'] is None,'Tooling failure phase must exit 2 without trace or result')
            require(phase.get('tampered_unchanged') is True,'Tampered state directory changed')
            continue
        if phase.get('crash'):require(phase['exit_code']==2 and phase['result'] is None,'Crash phase must exit 2 without a result')
        else:require(phase['exit_code']==0 and phase['result'] is not None,'Domain phase must exit 0 with a result')
        restored_cursor=None;restored_ids=None;restored_status='RUNNING'
        if kind=='resume':
            require(run_id is not None,'Resume without a prior phase')
            restored_ids=[worker_id for worker_id in WORKER_IDS if worker_id in recorded];restored_cursor=len(restored_ids)
            previous=flow['phases'][index-1].get('state');restored_status=previous['status'] if previous is not None else 'RUNNING'
        if kind=='replay':
            snapshot=phase.get('snapshot');require(snapshot is not None,'Replay phase must carry its snapshot document')
            require(validate_run_state_document(snapshot).valid and state_digest(canonical_state_body(snapshot))==snapshot['digest'],'Invalid replay snapshot')
            snapshot_recorded=_recorded(snapshot);restored_ids=list(snapshot_recorded);restored_cursor=len(restored_ids)
            require(restored_ids==list(WORKER_IDS[:restored_cursor]) and restored_cursor>0,'Snapshot must record a canonical prefix')
            for worker_id,outcome in snapshot_recorded.items():
                require(outcome['status']=='SUCCEEDED','Snapshot must record succeeded outcomes')
            require(normalize_state(phase['source_state'])==normalize_state(flow['phases'][index-1]['state']),'Replay mutated its source state')
            restored_status=snapshot['status']

        phase_run_id=phase['result']['run_id'] if phase['result'] is not None else (phase['state']['run_id'] if phase.get('state') is not None else None)
        require(phase_run_id is not None,'Phase lacks a run identity')
        if kind=='resume':require(phase_run_id==run_id,'Resume must continue the same run identity')
        if kind=='replay':require(phase_run_id!=run_id,'Replay must use a new run identity')
        context={'scenario_id':'order-brief-recovery','case_id':case['case_id'],'execution_mode':case['execution_mode'],'order_id':'ORD-1001','concurrency_limit':limit,'state_dir':phase['state_dir']}
        observed_peak=_validate_phase_events(phase,case,source,phase_run_id,context,limit,restored_ids,restored_status)
        if phase['result'] is not None:_validate_result(phase,case,limit,observed_peak,restored_cursor,restored_ids)
        if phase.get('state') is not None:
            document=phase['state']
            require(validate_run_state_document(document).valid and state_digest(canonical_state_body(document))==document['digest'],'Invalid state document')
            require(document['case_id']==case['case_id'] and document['execution_mode']==case['execution_mode'] and document['requested_order_id']=='ORD-1001' and document['concurrency_limit']==limit,'Wrong state binding')
            for worker_id,outcome in _recorded(document).items():
                if worker_id in recorded:require(recorded[worker_id]==outcome,'Re-executed or changed recorded outcome')
                recorded[worker_id]=outcome
        run_id=phase_run_id
    _assert_merged_identity(flow,case)
    _assert_final_state(flow,case)

def semantic_flow(flow,source):
    assert_flow_behavior(flow,source)
    workers={worker_id:[] for worker_id in WORKER_IDS};phases=[]
    for phase in flow['phases']:
        entry={'kind':phase['kind'],'run':[],'synthesis':[],'checkpoints':[],'completion_order':[]}
        for event in phase['events']:
            normalized=deepcopy(normalize_event(event));name=event['data'].get('step_name','')
            if name.startswith('worker.'):
                worker_id=name[7:];normalized.pop('sequence');workers[worker_id].append(normalized)
                if event['type']!='step.started':entry['completion_order'].append(worker_id)
            elif name=='synthesize':entry['synthesis'].append(normalized)
            elif event['type']=='checkpoint.saved':entry['checkpoints'].append(normalized)
            else:
                if isinstance(normalized.get('data'),dict):normalized['data'].pop('state_dir',None)
                entry['run'].append(normalized)
        phases.append(entry)
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

CASE_PHASES={'parallel-clean-complete':(('fresh',False),),
             'parallel-crash-resume':(('fresh',True),('resume',False)),
             'parallel-crash-resume-partial':(('fresh',True),('resume',False)),
             'parallel-cancel-resume':(('fresh',False),('resume',False)),
             'parallel-replay-from-checkpoint':(('fresh',False),('replay',False)),
             'parallel-corrupt-state':(('fresh',False),('corrupt-resume',False))}

def _normalize_result(result):
    return {key:value for key,value in normalize_result(result).items() if key!='state_dir'}

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
    require(code==2,'Tooling phase must exit 2')
    require(not [line for line in stdout.splitlines() if line.strip()],'Tooling phase must not print a result line')

def _run_flow(case,language,env,trace_dir):
    case_id=case['case_id']
    def command(options):
        if language=='typescript':return ['npm','--silent','--prefix',str(TS_ROOT),'run','run','--',*options]
        return [sys.executable,'-m','boundrelay_m4',*options]
    with tempfile.TemporaryDirectory() as tmp:
        state_dir=str(Path(tmp)/'state');run_id=None;phases=[]
        for kind,crash in CASE_PHASES[case_id]:
            trace=str((Path(trace_dir)/f'{case_id}.{language}.{kind}.jsonl').resolve())
            options=['--case',case_id,'--trace',trace,'--state-dir',state_dir]
            if kind=='corrupt-resume':
                tampered=str(Path(tmp)/'tampered');shutil.copytree(state_dir,tampered)
                state_path=next((Path(tampered)/name/'state.json' for name in sorted(os.listdir(tampered)) if (Path(tampered)/name/'state.json').is_file()),None)
                require(state_path is not None,'Missing state document to tamper')
                document=json.loads(state_path.read_text(encoding='utf-8'))
                require(document['steps'][1]['worker_id']=='payment-status' and document['steps'][1]['output']['payment_status']=='PAID','Unexpected tamper target')
                document['steps'][1]['output']['payment_status']='UNPAID'
                state_path.write_text(json.dumps(document),encoding='utf-8')
                tampered_bytes=state_path.read_text(encoding='utf-8')
                code,stdout,_=_spawn(command(['--case',case_id,'--trace',trace,'--state-dir',tampered,'--resume']),env)
                _cli_failure(code,stdout)
                require(state_path.read_text(encoding='utf-8')==tampered_bytes,'Tampered state directory changed')
                phases.append({'kind':kind,'crash':False,'exit_code':code,'result':None,'events':[],'trace_path':None,'state':None,'state_dir':tampered,'tampered_unchanged':True});continue
            if kind=='replay':options+=['--replay-from',str(Path(state_dir)/run_id/'checkpoints'/'step-1.json')]
            if kind=='resume':options.append('--resume')
            code,stdout,_=_spawn(command(options),env)
            if crash:
                _cli_failure(code,stdout)
                document=load_run_state(state_dir,_binding(case))['document'];run_id=document['run_id']
                phases.append({'kind':kind,'crash':True,'exit_code':code,'result':None,'events':read_jsonl(trace),'trace_path':trace,'state':document,'state_dir':state_dir});continue
            previous_run_id=run_id
            result=_cli_result(code,stdout);run_id=result['run_id']
            phase={'kind':kind,'crash':False,'exit_code':code,'result':result,'events':read_jsonl(trace),'trace_path':trace,'state_dir':state_dir,'state':None}
            if kind=='replay':
                source_dir=Path(state_dir)/previous_run_id
                phase['snapshot']=json.loads((source_dir/'checkpoints'/'step-1.json').read_text(encoding='utf-8'))
                phase['source_state']=load_run_state_document(source_dir/'state.json',_binding(case))
                phase['state']=load_run_state_document(Path(state_dir)/run_id/'state.json',_binding(case))
            else:phase['state']=load_run_state(state_dir,_binding(case))['document']
            phases.append(phase)
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
                       'trace_path':phase['trace_path'],'state':normalize_state(phase['state']) if phase.get('state') is not None else None} for phase in ts_flow['phases']]})
    require(len(records)==6,'Expected six case records')
    def phase_result(case_id,index):return flows[case_id]['phases'][index]['result']
    projection=business_projection(phase_result('parallel-clean-complete',0))
    for case_id,index in (('parallel-crash-resume',1),('parallel-cancel-resume',1),('parallel-replay-from-checkpoint',1)):
        require(business_projection(phase_result(case_id,index))==projection,f'Business projection mismatch: {case_id}')
    require(phase_result('parallel-crash-resume-partial',1)['status']=='PARTIAL','Partial case must stay PARTIAL')
    return records
