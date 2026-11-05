"""M8 verification gate helpers: exact-revision evidence over the M7 chain,
the isolated LangGraph mapping (six-case business parity, 38 mapping probes),
dependency isolation, and canonical-artifact immutability.

Mirrors tools/parity/verify_m7.py: evidence under .boundrelay/m8 is cleared
before any gate command, publication is refused on a moved HEAD, a dirty
worktree, tampered reports, stale lower evidence, isolation breaches, or
canonical-tree mutations, and every check survives python -O (require()/
RuntimeError, never the assert statement).
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from .verify_m5 import assert_clean_worktree,_revision

ROOT=Path(__file__).resolve().parents[2]
OUTPUT_ROOT=ROOT/'.boundrelay/m8'
EVIDENCE_PATH=OUTPUT_ROOT/'verification-evidence.json'
MAPPING_PYTHON=ROOT/'mappings/langgraph-m3/python'
MAPPING_SRC=MAPPING_PYTHON/'src'
MAPPING_TESTS=MAPPING_PYTHON/'tests'
TOTAL_MAPPING_TESTS=38
TOTAL_CONTRACT_PROBES=7
EXPECTED_LANGGRAPH_VERSION='1.2.20'
ISOLATION_SCAN_ROOTS=('lessons','contracts','tools','scripts','go')
# Case-insensitive: 'langgraph' also covers the package/import spellings.
ISOLATION_TOKENS=('langgraph','boundrelay_m3_langgraph','boundrelay-m3-langgraph')
ISOLATION_ALLOWLIST=(
    'tools/contracts/test_m8_contracts.py',
    'tools/parity/verify_m8.py',
    'tools/parity/test_m8_verification_safety.py',
    'scripts/verify_m8.py',
)
CANONICAL_ROOTS=('lessons','contracts','fixtures','go','tools','scripts')
# The M8 probe identities: the seven contracts probes plus the key mapping
# probes (three six-case parity probes, the taxonomy probes, and the naive
# regression probes). The full 38-test mapping suite must still pass; the
# required list pins the identities that carry the D-008 proof.
M8_CONTRACT_PROBE_IDS=(
    'tools.contracts.test_m8_contracts.M8IsolationContractTests.test_no_langgraph_references_outside_the_mapping',
    'tools.contracts.test_m8_contracts.M8ManifestContractTests.test_pyproject_names_the_mapping_package',
    'tools.contracts.test_m8_contracts.M8ManifestContractTests.test_requirements_pin_langgraph_exactly',
    'tools.contracts.test_m8_contracts.M8ManifestContractTests.test_mapping_package_skeleton_exists',
    'tools.contracts.test_m8_contracts.M8ManifestContractTests.test_pinned_langgraph_imports_in_this_venv',
    'tools.contracts.test_m8_contracts.M8ParityKeyContractTests.test_six_parity_case_keys_enumerated',
    'tools.contracts.test_m8_contracts.M8ParityKeyContractTests.test_every_parity_case_has_a_golden_projection',
)
M8_MAPPING_PROBE_IDS=(
    'test_graph_parity.SixCaseParityTests.test_business_projection_equals_golden_for_all_six_cases',
    'test_graph_parity.SixCaseParityTests.test_results_satisfy_the_closed_schema',
    'test_graph_parity.SixCaseParityTests.test_native_stream_trace_is_written',
    'test_taxonomy.TaxonomyTests.test_declared_failure_becomes_failed_outcome',
    'test_taxonomy.TaxonomyTests.test_invalid_output_never_becomes_a_fact',
    'test_taxonomy.TaxonomyTests.test_all_failed_blocks_synthesis',
    'test_naive_regression.NaiveDefaultPropagationTests.test_declared_error_crashes_the_graph_run',
    'test_naive_regression.NaiveDefaultPropagationTests.test_uncapped_dispatch_is_observed_not_normalized',
    'test_naive_regression.NaiveDefaultPropagationTests.test_invalid_output_becomes_a_fact_in_naive_mode',
)
REQUIRED_PROBE_IDS=M8_CONTRACT_PROBE_IDS+M8_MAPPING_PROBE_IDS

def require(condition,message):
    if not condition:raise AssertionError(message)

def clear_previous_evidence():
    target=OUTPUT_ROOT.absolute()
    if target.name!='m8' or target.resolve()!=target or target in (ROOT.resolve(),ROOT.parent.resolve()):
        raise RuntimeError('Unsafe evidence root')
    if target.exists():
        if not target.is_dir():raise RuntimeError('Unsafe evidence root')
        shutil.rmtree(target)

def validate_lower_evidence(revision):
    path=ROOT/'.boundrelay/m7/verification-evidence.json'
    try:proof=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as error:
        raise RuntimeError('m7 evidence is missing or unreadable') from error
    if proof.get('status')!='PASSED' or proof.get('revision')!=revision \
            or proof.get('milestone')!='m7':
        raise RuntimeError('m7 evidence is stale or failed for this revision')
def run_cli(command,env=None):
    print('+ '+' '.join(str(part) for part in command),flush=True)
    subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,check=True)

def _isolation_allowlisted(key):
    if key in ISOLATION_ALLOWLIST:return True
    # Compiled bytecode of an allowlisted source is the same artifact.
    parent,name=key.rsplit('/',1)
    if parent.endswith('__pycache__') and name.endswith('.pyc'):
        stem=name.split('.',1)[0]+'.py'
        source=f"{parent[:-len('__pycache__')]}{stem}"
        return source in ISOLATION_ALLOWLIST
    return False

def validate_isolation():
    """Fail-closed mirror of the contracts isolation scan: zero langgraph/
    mapping references outside mappings/langgraph-m3/ and the precise
    allowlist (lessons/, contracts/, tools/, scripts/, go/)."""
    offenders=[]
    for root in ISOLATION_SCAN_ROOTS:
        base=ROOT/root
        if not base.is_dir():raise RuntimeError(f'Missing isolation scan root: {base}')
        for path in sorted(base.rglob('*')):
            if not path.is_file():continue
            key=path.relative_to(ROOT).as_posix()
            if _isolation_allowlisted(key):continue
            try:text=path.read_text(encoding='utf-8',errors='replace').lower()
            except OSError as error:raise RuntimeError(f'Unreadable scan target: {path}') from error
            if any(token in text for token in ISOLATION_TOKENS):offenders.append(key)
    if offenders:
        raise RuntimeError('langgraph/mapping references outside mappings/langgraph-m3/ '
                           '(and outside the precise allowlist) break M8 isolation: '
                           +', '.join(offenders))
    return {'status':'matched','scanned_roots':list(ISOLATION_SCAN_ROOTS)}
def _canonical_files():
    for root in CANONICAL_ROOTS:
        base=ROOT/root
        if not base.is_dir():raise RuntimeError(f'Missing canonical root: {base}')
        for path in sorted(base.rglob('*')):
            if not path.is_file():continue
            if '__pycache__' in path.parts or path.suffix=='.pyc':continue
            yield path

def canonical_tree_snapshot():
    """Hash every canonical artifact (lessons/, contracts/, fixtures/, go/,
    tools/, scripts/ minus bytecode caches) so any mutation performed by a
    mapping run is detectable before publication."""
    snapshot={}
    for path in _canonical_files():
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[path.relative_to(ROOT).as_posix()]=digest
    require(snapshot,'Canonical tree snapshot must not be empty')
    return snapshot

def validate_canonical_tree(snapshot):
    """The canonical artifact tree must be byte-identical to the snapshot
    taken before the mapping suites ran."""
    current=canonical_tree_snapshot()
    added=sorted(set(current)-set(snapshot))
    removed=sorted(set(snapshot)-set(current))
    changed=sorted(key for key in set(current)&set(snapshot)
                   if current[key]!=snapshot[key])
    if added or removed or changed:
        details=[]
        if added:details.append('added: '+', '.join(added))
        if removed:details.append('removed: '+', '.join(removed))
        if changed:details.append('mutated: '+', '.join(changed))
        raise RuntimeError('Canonical artifacts changed during verification ('
                           +'; '.join(details)+')')
    return {'files':len(current),'status':'unchanged'}
def _run_proof_suite(discoveries,path_inserts=()):
    """Collect one probe suite with a child-visible import path (the mapping
    package is importable inside the run) and restore the parent's env."""
    import os
    added_paths=[str(entry) for entry in path_inserts if str(entry) not in sys.path]
    previous_env=os.environ.get('PYTHONPATH')
    try:
        for entry in added_paths:sys.path.insert(0,entry)
        if path_inserts:
            sources=os.pathsep.join(str(entry) for entry in path_inserts)
            os.environ['PYTHONPATH']=sources+(os.pathsep+previous_env if previous_env else '')
        discovered=[]
        def collect(suite):
            for test in suite:
                if isinstance(test,unittest.TestSuite):collect(test)
                else:discovered.append(test.id())
        suite=unittest.TestSuite()
        for directory,pattern,top_level in discoveries:
            suite.addTests(unittest.TestLoader().discover(str(directory),pattern=pattern,
                                                          top_level_dir=str(top_level)))
        collect(suite)
        if not discovered or any('_FailedTest' in name for name in discovered):
            raise RuntimeError('Empty or failed Python discovery')
        class ProofResult(unittest.TextTestResult):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);self.passed=[]
            def addSuccess(self,test):
                super().addSuccess(test);self.passed.append(test.id())
        result=unittest.TextTestRunner(verbosity=2,resultclass=ProofResult).run(suite)
        return {'successful':result.wasSuccessful(),'tests_run':result.testsRun,'discovered':discovered,
                'passed':result.passed,'failed':[test.id() for test,_ in result.failures+result.errors],
                'skipped':[test.id() for test,_ in result.skipped]}
    finally:
        for entry in added_paths:
            try:sys.path.remove(entry)
            except ValueError:pass
        if path_inserts:
            if previous_env is None:os.environ.pop('PYTHONPATH',None)
            else:os.environ['PYTHONPATH']=previous_env

def run_mapping_suite():
    """The 38-test mapping suite (unittest discover over
    mappings/langgraph-m3/python/tests, mapping src on the import path)."""
    return _run_proof_suite(((MAPPING_TESTS,'test_*.py',MAPPING_TESTS),),
                            path_inserts=(MAPPING_SRC,))

def run_contracts_suite():
    """The seven M8 contracts probes."""
    return _run_proof_suite(((ROOT/'tools/contracts','test_m8_contracts.py',ROOT),))
def validate_probe_reports(report,required=REQUIRED_PROBE_IDS,expected_tests=None):
    """Mirror of the M5/M6/M7 probe-report proof: the ProofResult collection
    must be fully green and contain every required probe identity."""
    try:
        if report['successful'] is not True or report['tests_run']<=0 or report['failed'] \
                or report['skipped'] or len(report['discovered'])!=report['tests_run'] \
                or set(report['discovered'])!=set(report['passed']) \
                or not set(required)<=set(report['passed']):
            raise ValueError('Required probe identities not passed')
        if expected_tests is not None and report['tests_run']!=expected_tests:
            raise ValueError(f'Probe suite must run exactly {expected_tests} tests, '
                             f'got {report["tests_run"]}')
        if any('_FailedTest' in name for name in report['discovered']):
            raise ValueError('Failed Python discovery')
        return {'tests':report['tests_run'],'passed_probes':sorted(set(required))}
    except (KeyError,TypeError,IndexError) as error:raise ValueError('Malformed test proof') from error

def langgraph_version():
    from importlib import metadata
    try:return metadata.version('langgraph')
    except Exception as error:raise RuntimeError('The pinned langgraph distribution is not importable') from error
def _validate_evidence_reports(evidence):
    """A tampered or incomplete report must never be publishable as PASSED
    evidence: mapping totals, contracts probes, combined probe identities,
    isolation status, canonical-tree status, and the exact langgraph pin are
    all re-verified here (RuntimeError, so -O cannot strip them)."""
    def reject(message):raise RuntimeError(message)
    suite=evidence.get('mapping_suite')
    if type(suite) is not dict:reject('Evidence must embed the mapping suite report')
    if suite.get('totals')!={'passed':TOTAL_MAPPING_TESTS,'failed':0,'skipped':0}:
        reject('Mapping suite must record 38 passed, 0 failed, 0 skipped tests')
    probes=suite.get('probes')
    if type(probes) is not dict or not set(M8_MAPPING_PROBE_IDS)<=set(probes.get('passed_probes') or ()):
        reject('Mapping suite proof must include every required mapping probe identity')
    contracts=evidence.get('contracts_probes')
    if type(contracts) is not dict or contracts.get('tests')!=TOTAL_CONTRACT_PROBES:
        reject('Contracts probes must record exactly 7 passing tests')
    combined=evidence.get('probe_reports')
    if type(combined) is not dict or not set(REQUIRED_PROBE_IDS)<=set(combined.get('passed_probes') or ()):
        reject('Probe reports must include every required M8 probe identity')
    isolation=evidence.get('isolation')
    if type(isolation) is not dict or isolation.get('status')!='matched':
        reject('Evidence must record matched dependency isolation')
    canonical=evidence.get('canonical_tree')
    if type(canonical) is not dict or canonical.get('status')!='unchanged':
        reject('Evidence must record an unchanged canonical artifact tree')
    runtimes=evidence.get('runtimes')
    if type(runtimes) is not dict or runtimes.get('langgraph')!=EXPECTED_LANGGRAPH_VERSION:
        reject(f'Evidence must record the exact langgraph pin {EXPECTED_LANGGRAPH_VERSION}')

def publish_evidence(evidence,starting_revision,canonical_snapshot=None):
    assert_clean_worktree()
    if _revision()!=starting_revision:raise RuntimeError('HEAD moved during verification')
    if evidence.get('revision')!=starting_revision or evidence.get('status')!='PASSED' \
            or evidence.get('milestone')!='m8':raise RuntimeError('Invalid evidence identity')
    _validate_evidence_reports(evidence)
    validate_lower_evidence(starting_revision)
    validate_isolation()
    # With the authority's pre-suite snapshot this re-checks the whole phase;
    # standalone it proves the tree is unchanged right now.
    validate_canonical_tree(canonical_snapshot if canonical_snapshot is not None
                            else canonical_tree_snapshot())
    EVIDENCE_PATH.parent.mkdir(parents=True,exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8')
