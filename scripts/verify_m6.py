"""M6 verification authority: exact-revision M6 certification over the full
M5 chain. Raw-first: evidence is only published by this script.

Sequence: clear .boundrelay/m6 -> clean worktree + starting SHA -> verify_m5
chain -> M6 probe suites (ProofResult collection) -> verifier-safety suite
(normal + python -O) -> evaluator over all 38 cases -> chaos over the full
matrix -> recheck clean HEAD -> publish .boundrelay/m6/verification-evidence.json.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.parity import verify_m6 as gate

PROBE_DISCOVERY=((ROOT/'tools/contracts','test_m6_contracts.py'),
                 (ROOT/'tools/parity','test_m6_evaluation.py'))

def run_python_suite():
    """Collect the M6 probe suites with a child-visible import path (lesson
    packages are importable inside the run) and restore the parent's env."""
    previous=os.environ.get('PYTHONPATH')
    sources=os.pathsep.join(str(path) for path in gate.LESSON_SRC_PATHS)
    os.environ['PYTHONPATH']=sources+(os.pathsep+previous if previous else '')
    try:return _collect_python_suite()
    finally:
        if previous is None:os.environ.pop('PYTHONPATH',None)
        else:os.environ['PYTHONPATH']=previous

def _collect_python_suite():
    discovered=[]
    def collect(suite):
        for test in suite:
            if isinstance(test,unittest.TestSuite):collect(test)
            else:discovered.append(test.id())
    suite=unittest.TestSuite()
    for directory,pattern in PROBE_DISCOVERY:
        suite.addTests(unittest.TestLoader().discover(str(directory),pattern=pattern,
                                                      top_level_dir=str(ROOT)))
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

def main():
    gate.clear_previous_evidence()
    gate.assert_clean_worktree()
    revision=gate._revision()
    gate.run_cli([sys.executable,'scripts/verify_m5.py'])
    gate.validate_lower_evidence(revision)
    gate.OUTPUT_ROOT.mkdir(parents=True,exist_ok=True)
    py_report=run_python_suite()
    probe_proof=gate.validate_probe_reports(py_report)
    (gate.OUTPUT_ROOT/'python-probes.json').write_text(json.dumps(py_report,indent=2)+'\n',encoding='utf-8')
    env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join(str(path) for path in gate.LESSON_SRC_PATHS)
    gate.run_cli([sys.executable,'-m','unittest','tools.parity.test_m6_verification_safety','-v'],env)
    gate.run_cli([sys.executable,'-O','-m','unittest','tools.parity.test_m6_verification_safety','-v'],env)
    evaluation=gate.run_evaluator()
    chaos_report=gate.run_chaos()
    (gate.OUTPUT_ROOT/'evaluation-report.json').write_text(json.dumps(evaluation,indent=2)+'\n',encoding='utf-8')
    (gate.OUTPUT_ROOT/'chaos-report.json').write_text(json.dumps(chaos_report,indent=2)+'\n',encoding='utf-8')
    version=lambda command:subprocess.check_output([shutil.which(command[0]) or command[0],
                                                    *command[1:]],cwd=ROOT,text=True).strip()
    evidence={'schema_version':'1.0','milestone':'m6','status':'PASSED','revision':revision,
              'command':'python scripts/verify_m6.py',
              'runtimes':{'python':platform.python_version(),'node':version(['node','--version']),
                          'npm':version(['npm','--version'])},
              'evaluation_report':{'totals':evaluation['totals'],'per_scenario':gate.scenario_counts(evaluation)},
              'chaos_report':{'totals':chaos_report['totals'],'rows':len(chaos_report['rows'])},
              'probe_reports':probe_proof,
              'test_commands':['python scripts/verify_m5.py',
                               'unittest probe discovery (contracts audit + evaluator/chaos probes)',
                               'python -m unittest tools.parity.test_m6_verification_safety',
                               'python -O -m unittest tools.parity.test_m6_verification_safety',
                               'python tools/evaluate.py --all','python tools/chaos.py --all']}
    gate.publish_evidence(evidence,revision)
    print(f'M6 verification PASSED at {revision}; cases38; matrix21; evidence: {gate.EVIDENCE_PATH}')
    return 0

if __name__=='__main__':raise SystemExit(main())
