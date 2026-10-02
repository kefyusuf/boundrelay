"""M2 exact-revision certification and semantic trace validation."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from jsonschema import Draft202012Validator, FormatChecker
import yaml
from tools.parity.normalize import normalize_result, normalized_trace, read_jsonl

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = ROOT / 'fixtures/scenarios/support-handoff.yaml'
TS_ROOT = ROOT / 'lessons/02-routing-handoff/typescript'
PY_SRC = ROOT / 'lessons/02-routing-handoff/python/src'
OUTPUT_ROOT = ROOT / '.boundrelay/m2'
EVIDENCE_PATH = OUTPUT_ROOT / 'verification-evidence.json'


def _schema(path):
    return Draft202012Validator(json.loads((ROOT / path).read_text(encoding='utf-8')), format_checker=FormatChecker())


_EVENT = _schema('contracts/events/run-event.schema.json')
_RESULT = _schema('contracts/results/handoff-result.schema.json')
_HANDOFF = _schema('contracts/handoffs/support-handoff.schema.json')
_ROUTE = _schema('contracts/routing/route-decision.schema.json')


def _validate(schema, value):
    errors = list(schema.iter_errors(value))
    if errors: raise AssertionError('; '.join(e.message for e in errors))


def assert_clean_worktree():
    changes = subprocess.check_output(['git','status','--porcelain=v1','--untracked-files=all'],cwd=ROOT,text=True).strip()
    if changes: raise RuntimeError('Revision-bound verification requires a clean Git worktree.\n'+changes)


def _revision():
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()


def clear_previous_evidence(output_root=OUTPUT_ROOT):
    shutil.rmtree(output_root,ignore_errors=True)


def publish_evidence(evidence, starting_revision, path=EVIDENCE_PATH):
    assert_clean_worktree()
    if _revision() != starting_revision: raise RuntimeError('HEAD moved during verification')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def assert_case_behavior(result, events, case, trace_path, source=None):
    _validate(_RESULT,result)
    assert result['case_id'] == case['id'], 'wrong case_id'
    assert result['router_mode'] == case['router_mode'], 'wrong router_mode'
    assert result['trace_path'] == trace_path, 'wrong trace_path'
    assert events, 'empty trace'
    expected_source = source or events[0]['source']
    ids = set()
    for sequence,event in enumerate(events,1):
        _validate(_EVENT,event)
        assert event['run_id'] == result['run_id'], 'wrong run_id'
        assert event['sequence'] == sequence, 'non-contiguous sequence'
        assert event['source'] == expected_source, 'wrong source'
        assert event['event_id'] not in ids, 'duplicate event_id'
        ids.add(event['event_id'])
    # INVALID_ROUTE_DECISION is unit-only; never used as a sixth certification case.
    invalid_route = result['failure_code'] == 'INVALID_ROUTE_DECISION'
    assert not invalid_route, 'canonical case unexpectedly rejected route'
    for key in ('status','proposed_route','selected_route','receiver','fallback_applied','specialist_invoked','failure_code'):
        assert result[key] == case['expected_'+key], f'wrong {key}'
    fallback = case['expected_confidence'] < .80
    selected = 'general' if fallback else case['expected_proposed_route']
    assert result['selected_route'] == selected and result['fallback_applied'] == fallback, 'wrong confidence policy'
    assert result['receiver'] == selected+'-specialist', 'wrong receiver mapping'
    succeeded = result['status'] == 'SUCCEEDED'
    expected_types = ['run.created','run.started'] + (['model.requested','model.completed'] if case['router_mode']=='model' else []) + ['route.selected','handoff.requested','handoff.accepted' if succeeded else 'handoff.rejected','run.completed' if succeeded else 'run.failed']
    assert [event['type'] for event in events] == expected_types, 'wrong lifecycle'
    assert events[0]['data'] == {'scenario_id':'support-handoff','case_id':case['id'],'router_mode':case['router_mode']}, 'wrong creation context'
    assert events[1]['data'] == {'case_id':case['id'],'router_mode':case['router_mode']}, 'wrong start context'
    by_type = {e['type']:e['data'] for e in events}
    if case['router_mode']=='model':
        assert by_type['model.requested'] == {'case_id':case['id']}, 'wrong model request'
        decision = {'route':case['expected_proposed_route'],'confidence':case['expected_confidence']}
        _validate(_ROUTE,by_type['model.completed']['decision'])
        assert by_type['model.completed'] == {'case_id':case['id'],'decision':decision}, 'wrong model decision'
    assert by_type['route.selected'] == {'router_mode':case['router_mode'],'proposed_route':case['expected_proposed_route'],'selected_route':selected,'confidence':case['expected_confidence'],'fallback_applied':fallback}, 'wrong selection payload'
    request = by_type['handoff.requested']
    assert set(request) == {'handoff_id','sender','receiver','sender_intent','receiver_input'}, 'wrong handoff request keys'
    assert request['sender'] == 'support-router' and request['receiver'] == result['receiver'], 'wrong handoff identities'
    assert request['sender_intent'] == {'route':case['expected_proposed_route'],'confidence':case['expected_confidence'],'policy_outcome':'fallback' if fallback else 'selected'}, 'wrong sender intent'
    context_loss = result['failure_code'] == 'HANDOFF_CONTEXT_INVALID'
    context = {'ticket_id':case['ticket_id'],**({} if context_loss else {'request_text':case['request']})}
    assert request['receiver_input'] == context, 'wrong receiver input'
    candidate = {'schema_version':'1.0',**request}
    if context_loss:
        errors = list(_HANDOFF.iter_errors(candidate))
        assert len(errors)==1 and errors[0].validator=='required' and list(errors[0].absolute_path)==['receiver_input'] and errors[0].validator_value==['ticket_id','request_text'], 'context loss must omit only request_text'
    else: _validate(_HANDOFF,candidate)
    boundary = 'handoff.accepted' if succeeded else 'handoff.rejected'
    assert by_type[boundary] == {'handoff_id':request['handoff_id'],'receiver':result['receiver'],**({} if succeeded else {'failure_code':result['failure_code']})}, 'wrong handoff boundary'
    terminal = {k:result[k] for k in ('status','proposed_route','selected_route','receiver','fallback_applied','specialist_invoked')}
    if not succeeded: terminal['failure_code']=result['failure_code']
    assert events[-1]['data']==terminal, 'terminal does not match result'


def _run(command, env=None):
    command = [shutil.which(command[0]) or command[0],*command[1:]]
    process = subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True,check=False)
    if process.returncode: raise RuntimeError(f'Command failed: {command}\n{process.stdout}\n{process.stderr}')
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if len(lines)!=1: raise RuntimeError('CLI must produce exactly one nonblank JSON line')
    def reject(value): raise ValueError('Nonstandard JSON constant: '+value)
    result=json.loads(lines[0],parse_constant=reject)
    if not isinstance(result,dict): raise RuntimeError('CLI result must be an object')
    return result


def main():
    clear_previous_evidence()
    assert_clean_worktree()
    revision = os.environ.get('BOUNDRELAY_M2_CANDIDATE_REVISION',_revision())
    if _revision()!=revision: raise RuntimeError('HEAD moved before M2 parity')
    # The lesson loader rejects malformed/duplicate/unknown cases before verification.
    sys.path.insert(0,str(PY_SRC))
    from boundrelay_m2.scenario import load_scenario
    cases = [asdict(c) for c in load_scenario().cases]
    env = os.environ.copy();env['PYTHONPATH']=str(PY_SRC)
    records=[]
    for case in cases:
        traces={language:str((OUTPUT_ROOT/'traces'/f"{case['id']}.{language}.jsonl").resolve()) for language in ('typescript','python')}
        ts=_run(['npm','--silent','--prefix',str(TS_ROOT),'run','run','--','--mode',case['router_mode'],'--case',case['id'],'--trace',traces['typescript']])
        py=_run([sys.executable,'-m','boundrelay_m2','--mode',case['router_mode'],'--case',case['id'],'--trace',traces['python']],env)
        for language,result in (('typescript',ts),('python',py)):
            assert_case_behavior(result,read_jsonl(traces[language]),case,traces[language],language)
        assert normalize_result(ts)==normalize_result(py), f"Result parity failed: {case['id']}"
        assert normalized_trace(traces['typescript'])==normalized_trace(traces['python']), f"Trace parity failed: {case['id']}"
        records.append({**normalize_result(ts),'typescript_trace':traces['typescript'],'python_trace':traces['python']})
    version=lambda command: subprocess.check_output([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,text=True).strip()
    evidence={'schema_version':'1.0','scenario_id':'support-handoff','status':'PASSED','revision':revision,'command':'python scripts/verify_m2.py','runtimes':{'python':platform.python_version(),'node':version(['node','--version']),'npm':version(['npm','--version'])},'cases':records}
    publish_evidence(evidence,revision)
    print(f'M2 verification PASSED at {revision}; evidence: {EVIDENCE_PATH}')
    return 0


if __name__=='__main__': raise SystemExit(main())
