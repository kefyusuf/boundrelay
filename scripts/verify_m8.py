"""M8 verification authority: exact-revision M8 certification over the full
M7 chain and the isolated LangGraph mapping. Raw-first: evidence is only
published by this script.

Sequence: clear .boundrelay/m8 -> clean worktree + starting SHA -> verify_m7
chain once -> M7 evidence validated -> canonical snapshot -> M8 contracts
probes (ProofResult collection) -> dependency isolation re-scan -> mapping
suite ProofResult (38 tests, six-case business parity) -> canonical tree
re-validated -> verifier-safety suite (normal + python -O) -> recheck clean
HEAD -> publish .boundrelay/m8/verification-evidence.json.
"""
import json
import os
import platform
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.parity import verify_m8 as gate

def main():
    gate.clear_previous_evidence()
    gate.assert_clean_worktree()
    revision=gate._revision()
    gate.run_cli([sys.executable,'scripts/verify_m7.py'])
    gate.validate_lower_evidence(revision)
    gate.OUTPUT_ROOT.mkdir(parents=True,exist_ok=True)
    snapshot=gate.canonical_tree_snapshot()
    contracts_report=gate.run_contracts_suite()
    contracts_proof=gate.validate_probe_reports(contracts_report,
        required=gate.M8_CONTRACT_PROBE_IDS,expected_tests=gate.TOTAL_CONTRACT_PROBES)
    (gate.OUTPUT_ROOT/'contracts-probes.json').write_text(
        json.dumps(contracts_report,indent=2)+'\n',encoding='utf-8')
    isolation=gate.validate_isolation()
    mapping_report=gate.run_mapping_suite()
    mapping_proof=gate.validate_probe_reports(mapping_report,
        required=gate.M8_MAPPING_PROBE_IDS,expected_tests=gate.TOTAL_MAPPING_TESTS)
    (gate.OUTPUT_ROOT/'mapping-suite.json').write_text(
        json.dumps(mapping_report,indent=2)+'\n',encoding='utf-8')
    canonical=gate.validate_canonical_tree(snapshot)
    env=os.environ.copy()
    gate.run_cli([sys.executable,'-m','unittest','tools.parity.test_m8_verification_safety','-v'],env)
    gate.run_cli([sys.executable,'-O','-m','unittest','tools.parity.test_m8_verification_safety','-v'],env)
    combined={'successful':contracts_report['successful'] and mapping_report['successful'],
              'tests_run':contracts_report['tests_run']+mapping_report['tests_run'],
              'discovered':contracts_report['discovered']+mapping_report['discovered'],
              'passed':contracts_report['passed']+mapping_report['passed'],
              'failed':contracts_report['failed']+mapping_report['failed'],
              'skipped':contracts_report['skipped']+mapping_report['skipped']}
    probe_proof=gate.validate_probe_reports(combined)
    evidence={'schema_version':'1.0','milestone':'m8','status':'PASSED','revision':revision,
              'command':'python scripts/verify_m8.py',
              'runtimes':{'python':platform.python_version(),
                          'langgraph':gate.langgraph_version()},
              'isolation':isolation,
              'canonical_tree':canonical,
              'contracts_probes':contracts_proof,
              'mapping_suite':{'totals':{'passed':mapping_report['tests_run'],
                                         'failed':len(mapping_report['failed']),
                                         'skipped':len(mapping_report['skipped'])},
                               'probes':mapping_proof},
              'probe_reports':probe_proof,
              'test_commands':['python scripts/verify_m7.py',
                               'unittest probe discovery (M8 contracts + mapping suite)',
                               'python -m unittest tools.parity.test_m8_verification_safety',
                               'python -O -m unittest tools.parity.test_m8_verification_safety']}
    gate.publish_evidence(evidence,revision,canonical_snapshot=snapshot)
    print(f'M8 verification PASSED at {revision}; mapping suite '
          f'{mapping_report["tests_run"]}/{len(mapping_report["failed"])} failed; '
          f'isolation matched; evidence: {gate.EVIDENCE_PATH}')
    return 0

if __name__=='__main__':raise SystemExit(main())
