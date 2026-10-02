from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / '.boundrelay/m2'
TS = ROOT / 'lessons/02-routing-handoff/typescript'
PY_SRC = ROOT / 'lessons/02-routing-handoff/python/src'
PY_TESTS = ROOT / 'lessons/02-routing-handoff/python/tests'


def run(command,env=None):
    print('+ '+' '.join(command),flush=True)
    subprocess.run([shutil.which(command[0]) or command[0],*command[1:]],cwd=ROOT,env=env,check=True)


def main():
    # Ensure project imports work when invoked by filename from any directory.
    sys.path.insert(0,str(ROOT))
    from tools.parity.verify_m2 import assert_clean_worktree, _revision, clear_previous_evidence
    clear_previous_evidence()
    assert_clean_worktree()
    revision=_revision()
    env=os.environ.copy();env['PYTHONPATH']=str(PY_SRC);env['BOUNDRELAY_M2_CANDIDATE_REVISION']=revision
    run([sys.executable,'scripts/verify_m1.py'])
    run([sys.executable,'-m','unittest','tools.contracts.test_m2_contracts','-v'],env)
    run(['npm','--prefix',str(TS),'run','typecheck'])
    run(['npm','--prefix',str(TS),'test'])
    run([sys.executable,'-m','unittest','discover','-s',str(PY_TESTS),'-v'],env)
    run([sys.executable,'-m','unittest','tools.parity.test_normalize','tools.parity.test_trace_contract','tools.parity.test_m2_verification_safety','tools.parity.test_command_portability','-v'],env)
    run([sys.executable,'-m','tools.parity.verify_m2'],env)
    return 0


if __name__=='__main__': raise SystemExit(main())
