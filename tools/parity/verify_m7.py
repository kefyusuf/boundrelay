"""M7 verification gate helpers: exact-revision evidence over the M6 chain,
the three-language evaluator (38 cases, 13 with Go), the full failure matrix,
the Go module gates, and the checked-in Go fixture projections.

Mirrors tools/parity/verify_m6.py: evidence under .boundrelay/m7 is cleared
before any gate command, publication is refused on a moved HEAD, a dirty
worktree, tampered reports, stale lower evidence, Go projection drift, or Go
gate failures, and every check survives python -O (require()/RuntimeError,
never the assert statement).
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

from .verify_m5 import assert_clean_worktree,_revision

ROOT=Path(__file__).resolve().parents[2]
OUTPUT_ROOT=ROOT/'.boundrelay/m7'
EVIDENCE_PATH=OUTPUT_ROOT/'verification-evidence.json'
GO_ROOT=ROOT/'go'
sys.path.insert(0,str(ROOT))
from tools import chaos
from tools import evaluate as ev

LESSON_SRC_PATHS=tuple(ev.PY_SRC)
TOTAL_CASES=38
TOTAL_ROWS=21
THREE_LANGUAGE_CASES=13
# The M7 probe identities: the contracts projection/pin probes plus the
# language-extension probes from tools/parity/test_m6_evaluation.py.
M7_CONTRACT_PROBE_IDS=('tools.contracts.test_m7_contracts.M7ProjectionContractTests.test_projections_match_yaml_sources',
                       'tools.contracts.test_m7_contracts.M7CaseKeyEnumerationTests.test_case_keys_enumerated',
                       'tools.contracts.test_m7_contracts.M7ModulePinTests.test_go_module_pins')
M7_LANGUAGE_PROBE_IDS=tuple(
    f'tools.parity.test_m6_evaluation.M7LanguageExtensionTests.test_{name}' for name in (
        'go_flow_runner_builds_once_and_reuses',
        'go_flow_runner_build_failure_is_a_tooling_error',
        'go_flow_runner_runs_real_m0_and_m3_cases',
        'go_flow_runner_divergence_is_a_tooling_error',
        'evaluate_languages_flag_semantics',
        'go_for_non_go_scenario_is_a_tooling_error',
        'non_go_scenarios_forced_down_to_ts_py',
        'matrix_go_proofs',
        'matrix_go_unit_row_replay'))
REQUIRED_PROBE_IDS=M7_CONTRACT_PROBE_IDS+M7_LANGUAGE_PROBE_IDS
GO_PROJECTION_SCENARIOS=('support-triage','order-brief')

def require(condition,message):
    if not condition:raise AssertionError(message)

def clear_previous_evidence():
    target=OUTPUT_ROOT.absolute()
    if target.name!='m7' or target.resolve()!=target or target in (ROOT.resolve(),ROOT.parent.resolve()):
        raise RuntimeError('Unsafe evidence root')
    if target.exists():
        if not target.is_dir():raise RuntimeError('Unsafe evidence root')
        shutil.rmtree(target)

def validate_lower_evidence(revision):
    path=ROOT/'.boundrelay/m6/verification-evidence.json'
    try:proof=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as error:
        raise RuntimeError('m6 evidence is missing or unreadable') from error
    if proof.get('status')!='PASSED' or proof.get('revision')!=revision \
            or proof.get('milestone')!='m6':
        raise RuntimeError('m6 evidence is stale or failed for this revision')

def run_cli(command,env=None):
    print('+ '+' '.join(str(part) for part in command),flush=True)
    subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,check=True)

def _run_tool(command,cwd):
    print('+',' '.join(str(part) for part in command),flush=True)
    process=subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],
                           cwd=str(cwd),text=True,capture_output=True)
    if process.returncode!=0:
        raise RuntimeError(f'{" ".join(str(part) for part in command)} failed '
                           f'(exit {process.returncode}): {process.stderr.strip()[:400]}')
    return process.stdout

def run_go_gates():
    """The Go module gates from go/: vet, test, and gofmt cleanliness;
    formatting drift blocks certification."""
    _run_tool(['go','vet','./...'],GO_ROOT)
    _run_tool(['go','test','./...'],GO_ROOT)
    drift=_run_tool(['gofmt','-l','.'],GO_ROOT)
    if drift.strip():
        raise RuntimeError('gofmt drift detected in go/ (run gofmt -w): '+drift.strip())
    return {'vet':'clean','test':'ok','gofmt':'clean'}

def validate_projections():
    """The checked-in Go fixture projections must deep-equal the YAML sources
    they were generated from: the reviewer-visible bridge the Go runtimes
    consume. Drift refuses certification."""
    failures=[]
    for scenario in GO_PROJECTION_SCENARIOS:
        source=yaml.safe_load(
            (ROOT/f'fixtures/scenarios/{scenario}.yaml').read_text(encoding='utf-8'))
        base=ROOT/f'fixtures/goprojections/{scenario}'
        if json.loads((base/'scenario.json').read_text(encoding='utf-8'))!=source:
            failures.append(f'{scenario}/scenario.json drifts from the YAML source')
        if json.loads((base/'attribution.json').read_text(encoding='utf-8'))!=source.get('attribution'):
            failures.append(f'{scenario}/attribution.json drifts from the YAML source')
        workers=json.loads((base/'workers.json').read_text(encoding='utf-8'))
        references=[]
        for case in source.get('cases') or []:
            reference=case.get('worker_fixture') if isinstance(case,dict) else None
            if reference and reference not in references:references.append(reference)
        if sorted(workers)!=sorted(references):
            failures.append(f'{scenario}/workers.json must cover exactly the referenced fixtures')
        for reference,content in workers.items():
            fixture=yaml.safe_load((ROOT/reference).read_text(encoding='utf-8'))
            if content!=fixture:
                failures.append(f'{scenario}: worker projection {reference} drifts from the YAML source')
    if failures:
        raise RuntimeError('Go fixture projections diverge: '+'; '.join(failures))
    return {'scenarios':list(GO_PROJECTION_SCENARIOS),'status':'matched'}

def run_go_flows():
    """The 13 canonical M0/M3 case keys through the evaluator with
    languages ts,py,go; every case must PASS three-language."""
    report=ev.evaluate(scenarios=list(ev.GO_SCENARIOS),languages=('ts','py','go'))
    require(report.get('totals')=={'passed':THREE_LANGUAGE_CASES,'failed':0},
            f'Go flows must pass all {THREE_LANGUAGE_CASES} three-language cases, '
            f'got {report.get("totals")}')
    three=[record for record in report.get('cases') or []
           if 'go' in (record.get('languages') or [])]
    require(len(three)==THREE_LANGUAGE_CASES,
            f'Go flows must cover {THREE_LANGUAGE_CASES} three-language cases, got {len(three)}')
    return report

def run_evaluator():
    """The full evaluator over all 38 canonical cases three-language where
    available: 38 passed, 0 failed, exactly 13 with Go."""
    report=ev.evaluate(scenarios=None,languages=('ts','py','go'))
    require(report.get('totals')=={'passed':TOTAL_CASES,'failed':0},
            f'Evaluator must pass all {TOTAL_CASES} canonical cases, got {report.get("totals")}')
    require(len(report.get('cases') or ())==TOTAL_CASES,
            f'Evaluator must cover {TOTAL_CASES} cases, got {len(report.get("cases") or ())}')
    three=[record for record in report.get('cases') or []
           if 'go' in (record.get('languages') or [])]
    require(len(three)==THREE_LANGUAGE_CASES,
            f'Evaluator must run {THREE_LANGUAGE_CASES} cases three-language, got {len(three)}')
    return report

def run_chaos():
    """Replay the full failure matrix live; totals must be 21/0."""
    report=chaos.replay_matrix()
    require(report.get('totals')=={'passed':TOTAL_ROWS,'failed':0},
            f'Chaos must pass all {TOTAL_ROWS} matrix rows, got {report.get("totals")}')
    require(len(report.get('rows') or ())==TOTAL_ROWS,'Chaos must replay the full failure matrix')
    return report

def scenario_counts(report):
    counts={}
    for record in report.get('cases') or []:
        entry=counts.setdefault(record.get('scenario_id'),{'passed':0,'failed':0})
        entry['passed' if record.get('status')=='PASS' else 'failed']+=1
    return counts

def validate_probe_reports(report):
    """Mirror of the M5/M6 probe-report proof: the ProofResult collection
    from the probe suites must be fully green and contain every required M7
    probe identity (3 contracts probes + 9 language-extension probes)."""
    try:
        if report['successful'] is not True or report['tests_run']<=0 or report['failed'] \
                or report['skipped'] or len(report['discovered'])!=report['tests_run'] \
                or set(report['discovered'])!=set(report['passed']) \
                or not set(REQUIRED_PROBE_IDS)<=set(report['passed']):
            raise ValueError('Required M7 probe identities not passed')
        if any('_FailedTest' in name for name in report['discovered']):
            raise ValueError('Failed Python discovery')
        return {'tests':report['tests_run'],'passed_probes':sorted(REQUIRED_PROBE_IDS)}
    except (KeyError,TypeError,IndexError) as error:raise ValueError('Malformed test proof') from error

def _validate_evidence_reports(evidence):
    """A tampered or incomplete report must never be publishable as PASSED
    evidence: totals, per-scenario counts, the three-language count, chaos
    totals, Go gates, and probe identities are all re-verified here
    (RuntimeError, so -O cannot strip them)."""
    def reject(message):raise RuntimeError(message)
    report=evidence.get('evaluation_report')
    if type(report) is not dict:reject('Evidence must embed the evaluation report')
    if report.get('totals')!={'passed':TOTAL_CASES,'failed':0}:
        reject('Evaluation report must record 38 passed and 0 failed cases')
    counts=report.get('per_scenario')
    if type(counts) is not dict or set(counts)!=set(ev.SCENARIOS):
        reject('Evaluation report must count every scenario')
    if any(count.get('failed')!=0 for count in counts.values()) \
            or sum(count.get('passed',0) for count in counts.values())!=TOTAL_CASES:
        reject('Per-scenario counts must sum to 38 passed cases with zero failures')
    if report.get('three_language_cases')!=THREE_LANGUAGE_CASES:
        reject('Evaluation report must record exactly 13 three-language cases')
    go_flows=evidence.get('go_flows')
    if type(go_flows) is not dict or go_flows.get('totals')!={'passed':THREE_LANGUAGE_CASES,'failed':0}:
        reject('Go flow report must record 13 passed and 0 failed three-language cases')
    chaos_report=evidence.get('chaos_report')
    if type(chaos_report) is not dict or chaos_report.get('totals')!={'passed':TOTAL_ROWS,'failed':0}:
        reject('Chaos report must record 21 passed and 0 failed rows')
    go_gates=evidence.get('go_gates')
    if type(go_gates) is not dict or set(go_gates)!={'vet','test','gofmt'} \
            or any(value!='clean' for key,value in go_gates.items() if key!='test') \
            or go_gates.get('test') not in ('ok','clean'):
        reject('Go gates must be recorded clean (vet/test/gofmt)')
    projections=evidence.get('projections')
    if type(projections) is not dict or projections.get('status')!='matched':
        reject('Evidence must record matched Go fixture projections')
    probes=evidence.get('probe_reports')
    if type(probes) is not dict or not set(REQUIRED_PROBE_IDS)<=set(probes.get('passed_probes') or ()):
        reject('Probe reports must include every required M7 probe identity')

def publish_evidence(evidence,starting_revision):
    assert_clean_worktree()
    if _revision()!=starting_revision:raise RuntimeError('HEAD moved during verification')
    if evidence.get('revision')!=starting_revision or evidence.get('status')!='PASSED' \
            or evidence.get('milestone')!='m7':raise RuntimeError('Invalid evidence identity')
    _validate_evidence_reports(evidence)
    validate_lower_evidence(starting_revision)
    validate_projections()
    EVIDENCE_PATH.parent.mkdir(parents=True,exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8')
