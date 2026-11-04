"""M6 verification gate helpers: exact-revision evidence over the M5 chain,
the evaluator's 38 canonical cases, and the full failure matrix.

Mirrors tools/parity/verify_m5.py: evidence under .boundrelay/m6 is cleared
before any gate command, publication is refused on a moved HEAD, a dirty
worktree, tampered reports, or stale lower evidence, and every check survives
python -O (require()/RuntimeError, never the assert statement).
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .verify_m5 import assert_clean_worktree,_revision

ROOT=Path(__file__).resolve().parents[2]
OUTPUT_ROOT=ROOT/'.boundrelay/m6'
EVIDENCE_PATH=OUTPUT_ROOT/'verification-evidence.json'
sys.path.insert(0,str(ROOT))
from tools import chaos
from tools import evaluate as ev

LESSON_SRC_PATHS=tuple(ev.PY_SRC)
# The 13 fail-closed evaluator/chaos probes from tools/parity/test_m6_evaluation.py
# plus the contract audit probes from tools/contracts/test_m6_contracts.py.
EVALUATOR_PROBES=('missing_golden_is_a_tooling_error','language_run_failure_is_a_tooling_error',
                  'language_divergence_is_a_tooling_error','regenerate_refuses_behavior_bearing_changes',
                  'regenerate_tolerates_harness_only_changes','report_shape_on_success',
                  'attribution_totals_drift_is_a_tooling_error','missing_step_attribution_is_a_tooling_error',
                  'main_exit_semantics','matrix_covers_every_declared_failure_class',
                  'matrix_rows_have_stable_ids','chaos_replay_matches_matrix','chaos_exercises_all_rows')
CONTRACT_PROBE_IDS=('tools.contracts.test_m6_contracts.M6AttributionContractTests.test_attribution_schema_and_tables',
                    'tools.contracts.test_m6_contracts.M6EventSurfaceAuditTests.test_event_surface_audit',
                    'tools.contracts.test_m6_contracts.M6EventSurfaceAuditTests.test_result_schemas_embed_the_canonical_attribution_block')
EVALUATOR_PROBE_IDS=tuple(f'tools.parity.test_m6_evaluation.M6EvaluationSafetyTests.test_{name}'
                          for name in EVALUATOR_PROBES)
REQUIRED_PROBE_IDS=CONTRACT_PROBE_IDS+EVALUATOR_PROBE_IDS
TOTAL_CASES=38
TOTAL_ROWS=21

def require(condition,message):
    if not condition:raise AssertionError(message)

def clear_previous_evidence():
    target=OUTPUT_ROOT.absolute()
    if target.name!='m6' or target.resolve()!=target or target in (ROOT.resolve(),ROOT.parent.resolve()):
        raise RuntimeError('Unsafe evidence root')
    if target.exists():
        if not target.is_dir():raise RuntimeError('Unsafe evidence root')
        shutil.rmtree(target)

def validate_lower_evidence(revision):
    path=ROOT/'.boundrelay/m5/verification-evidence.json'
    proof=json.loads(path.read_text(encoding='utf-8'))
    if proof.get('status')!='PASSED' or proof.get('revision')!=revision:
        raise RuntimeError('m5 evidence is stale or failed for this revision')

def run_cli(command,env=None):
    print('+ '+' '.join(str(part) for part in command),flush=True)
    subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,check=True)

def run_evaluator():
    """Run the real evaluator over all 38 canonical cases (report to a temp
    path); the returned report dict is what the evidence captures."""
    with tempfile.TemporaryDirectory() as directory:
        report=ev.evaluate(scenarios=None,report_path=Path(directory)/'evaluation-report.json')
    require(report.get('totals')=={'passed':TOTAL_CASES,'failed':0},
            f'Evaluator must pass all {TOTAL_CASES} canonical cases, got {report.get("totals")}')
    require(len(report.get('cases') or ())==TOTAL_CASES,
            f'Evaluator must cover {TOTAL_CASES} cases, got {len(report.get("cases") or ())}')
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
    """Mirror of the M5 probe-report proof: the ProofResult collection from
    the probe suites must be fully green and contain every required M6
    probe identity (13 evaluator/chaos probes + the contract audit probes)."""
    try:
        if report['successful'] is not True or report['tests_run']<=0 or report['failed'] \
                or report['skipped'] or len(report['discovered'])!=report['tests_run'] \
                or set(report['discovered'])!=set(report['passed']) \
                or not set(REQUIRED_PROBE_IDS)<=set(report['passed']):
            raise ValueError('Required M6 probe identities not passed')
        if any('_FailedTest' in name for name in report['discovered']):
            raise ValueError('Failed Python discovery')
        return {'tests':report['tests_run'],'passed_probes':sorted(REQUIRED_PROBE_IDS)}
    except (KeyError,TypeError,IndexError) as error:raise ValueError('Malformed test proof') from error

def _validate_evidence_reports(evidence):
    """A tampered or incomplete report must never be publishable as PASSED
    evidence: totals, per-scenario counts, chaos totals, and probe identities
    are all re-verified here (RuntimeError, so -O cannot strip them)."""
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
    chaos_report=evidence.get('chaos_report')
    if type(chaos_report) is not dict or chaos_report.get('totals')!={'passed':TOTAL_ROWS,'failed':0}:
        reject('Chaos report must record 21 passed and 0 failed rows')
    probes=evidence.get('probe_reports')
    if type(probes) is not dict or not set(REQUIRED_PROBE_IDS)<=set(probes.get('passed_probes') or ()):
        reject('Probe reports must include every required M6 probe identity')

def publish_evidence(evidence,starting_revision):
    assert_clean_worktree()
    if _revision()!=starting_revision:raise RuntimeError('HEAD moved during verification')
    if evidence.get('revision')!=starting_revision or evidence.get('status')!='PASSED' \
            or evidence.get('milestone')!='m6':raise RuntimeError('Invalid evidence identity')
    _validate_evidence_reports(evidence)
    validate_lower_evidence(starting_revision)
    EVIDENCE_PATH.parent.mkdir(parents=True,exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8')
