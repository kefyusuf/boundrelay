import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.parity import verify_m3 as gate
PY_TESTS=ROOT/'lessons/03-parallel-fanout-fanin/python/tests'

def run(command,env=None):
    print('+ '+' '.join(command),flush=True)
    subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,check=True)

def run_python_suite():
    discovered=[]
    def collect(suite):
        for test in suite:
            if isinstance(test,unittest.TestSuite):collect(test)
            else:discovered.append(test.id())
    suite=unittest.TestLoader().discover(str(PY_TESTS));collect(suite)
    if not discovered or any('_FailedTest' in name for name in discovered):raise RuntimeError('Empty or failed Python discovery')
    class ProofResult(unittest.TextTestResult):
        def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.passed=[]
        def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())
    result=unittest.TextTestRunner(verbosity=2,resultclass=ProofResult).run(suite)
    return {'successful':result.wasSuccessful(),'tests_run':result.testsRun,'discovered':discovered,'passed':result.passed,
            'failed':[test.id() for test,_ in result.failures+result.errors],'skipped':[test.id() for test,_ in result.skipped]}

def main():
    gate.assert_clean_worktree();revision=gate._revision();gate.clear_previous_evidence()
    env=os.environ.copy();env['PYTHONPATH']=str(gate.PY_SRC)
    run([sys.executable,'scripts/verify_m2.py']);gate.validate_lower_evidence(revision)
    run([sys.executable,'-m','unittest','tools.contracts.test_m3_contracts','-v'],env)
    run(['npm','--prefix',str(gate.TS_ROOT),'run','typecheck'])
    gate.OUTPUT_ROOT.mkdir(parents=True,exist_ok=True)
    ts_path=gate.OUTPUT_ROOT/'typescript-tests.json'
    run(['npm','--prefix',str(gate.TS_ROOT),'test','--','--reporter=json','--outputFile='+str(ts_path)])
    py_report=run_python_suite();(gate.OUTPUT_ROOT/'python-tests.json').write_text(json.dumps(py_report,indent=2)+'\n',encoding='utf-8')
    test_proof=gate.validate_probe_reports(json.loads(ts_path.read_text(encoding='utf-8')),py_report)
    run([sys.executable,'-m','unittest','tools.parity.test_m3_verification_safety','-v'],env)
    run([sys.executable,'-O','-m','unittest','tools.parity.test_m3_verification_safety','-v'],env)
    records=gate.verify_cases()
    version=lambda command:subprocess.check_output([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,text=True).strip()
    evidence={'schema_version':'1.0','scenario_id':'order-brief','status':'PASSED','revision':revision,'command':'python scripts/verify_m3.py',
              'runtimes':{'python':platform.python_version(),'node':version(['node','--version']),'npm':version(['npm','--version'])},
              'test_proof':test_proof,'test_commands':['npm test -- --reporter=json','unittest discovery with per-test success records','python -m unittest tools.parity.test_m3_verification_safety','python -O -m unittest tools.parity.test_m3_verification_safety'],
              'cases':records}
    gate.publish_evidence(evidence,revision)
    print(f'M3 verification PASSED at {revision}; cases6/traces12; evidence: {gate.EVIDENCE_PATH}')
    return 0

if __name__=='__main__':raise SystemExit(main())
