"""M6 verifier-safety suite: mutations that must fail before M6 evidence is
published, plus the M5-mirrored publication/property checks. All evaluator
and chaos invocations patch the subprocess boundary (ev.run_flow) or the
report producers, so the suite stays fast and never reruns the real flows;
scripts/verify_m6.py performs the real runs."""
from copy import deepcopy
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from itertools import count
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools import chaos
from tools import evaluate as ev
from tools.parity import verify_m6 as gate
from tools.parity.test_m6_evaluation import canned_flow

SCENARIO='support-triage';CASE_KEY='billing-duplicate-charge@model'
COUNTS={'support-triage':7,'order-investigation':8,'support-handoff':5,
        'order-brief':6,'order-brief-recovery':6,'order-closure':6}

def golden_for(flow):
    actual=ev.flow_evidence(flow)
    return {'scenario_id':SCENARIO,'case_key':CASE_KEY,
            'languages':['typescript','python'],**actual}

def write_golden(root,golden):
    path=Path(root)/SCENARIO/f'{CASE_KEY}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(golden,indent=2)+'\n',encoding='utf-8')
    return path

def evaluation(flow=None,golden=None):
    """Run the real evaluator with the subprocess boundary faked."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root=Path(directory)
        with patch.object(ev,'GOLDEN_ROOT',root/'goldens'), \
             patch.object(ev,'run_flow',return_value=flow or canned_flow()):
            if golden is not None:write_golden(root/'goldens',golden)
            return ev.evaluate([SCENARIO],only_case=CASE_KEY)

def full_report():
    cases=[{'scenario_id':name,'case_key':f'{name}-{index}','status':'PASS'}
           for name,number in COUNTS.items() for index in range(number)]
    return {'totals':{'passed':gate.TOTAL_CASES,'failed':0},'cases':cases}

class M6VerificationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.path=str(self.root/'trace.jsonl')
        self.counter=count()

    def test_golden_attribution_tampering_fails_evaluation(self):
        honest=golden_for(canned_flow())
        tampered=deepcopy(honest);tampered['attribution']['totals']['latency_ms']+=1
        report=evaluation(golden=tampered)
        self.assertEqual(report['totals'],{'passed':0,'failed':1})
        self.assertEqual(report['cases'][0]['status'],'FAIL')
        self.assertIn('Golden divergence',report['cases'][0]['error'])
        self.assertIn('attribution',report['cases'][0]['error'])
        self.assertEqual(evaluation(golden=honest)['totals'],{'passed':1,'failed':0})

    def test_golden_result_projection_tampering_fails_evaluation(self):
        honest=golden_for(canned_flow())
        tampered=deepcopy(honest);tampered['result_projection']['status']='FAILED'
        report=evaluation(golden=tampered)
        self.assertEqual(report['totals'],{'passed':0,'failed':1})
        self.assertIn('result_projection',report['cases'][0]['error'])

    def test_result_totals_drift_fails_evaluation(self):
        drifted=canned_flow()
        drifted['result']['attribution']['totals']['latency_ms']+=1
        drifted['ts_result']['attribution']['totals']['latency_ms']+=1
        report=evaluation(flow=drifted,golden=golden_for(canned_flow()))
        self.assertEqual(report['totals'],{'passed':0,'failed':1})
        self.assertIn('do not equal the per-step sum',report['cases'][0]['error'])

    def test_matrix_row_without_proof_fails_coverage(self):
        row=deepcopy(next(r for r in chaos.load_matrix()['rows'] if r.get('case_key') is None))
        for language in ('python','typescript'):
            self.assertFalse(chaos.proof_identity_exists(row['lesson'],language,
                                                         'nonexistent-m6-proof-identity'))
        row['proof']={language:'nonexistent-m6-proof-identity'
                      for language in ('python','typescript')}
        report=chaos.replay_matrix(rows=[row])
        self.assertEqual(report['totals'],{'passed':0,'failed':1})
        self.assertIn('proof identity missing',report['rows'][0]['problems'][0])

    def test_chaos_response_mismatch_fails_replay(self):
        row=deepcopy(next(r for r in chaos.load_matrix()['rows']
                          if r.get('case_key')=='invalid-model-route@model'))
        flow={'result':{'status':'FAILED','failure_code':'INVALID_ROUTE_DECISION',
                        'specialist_invoked':False,'run_id':'run-1'},
              'ts_result':{'status':'FAILED','failure_code':'INVALID_ROUTE_DECISION',
                           'specialist_invoked':False,'run_id':'run-2'},
              'events':[],'ts_events':[]}
        with patch.object(ev,'run_flow',return_value=flow):
            self.assertEqual(chaos.replay_matrix(rows=[row])['totals'],
                             {'passed':1,'failed':0})
            tampered=deepcopy(row);tampered['expected_response']['status']='SUCCEEDED'
            report=chaos.replay_matrix(rows=[tampered])
        self.assertEqual(report['totals'],{'passed':0,'failed':1})
        self.assertIn('status',report['rows'][0]['problems'][0])

    def test_gate_helpers_reject_incomplete_reports(self):
        with patch.object(ev,'evaluate',return_value=full_report())as fake:
            self.assertEqual(gate.run_evaluator(),fake.return_value)
        with patch.object(ev,'evaluate',return_value={'totals':{'passed':37,'failed':1},'cases':[]}):
            with self.assertRaises(AssertionError):gate.run_evaluator()
        short=full_report();short['cases']=short['cases'][:-1]
        with patch.object(ev,'evaluate',return_value=short):
            with self.assertRaises(AssertionError):gate.run_evaluator()
        rows=[{'failure_id':f'M0-F{index}'} for index in range(gate.TOTAL_ROWS)]
        with patch.object(chaos,'replay_matrix',return_value={'rows':rows,'totals':{'passed':gate.TOTAL_ROWS,'failed':0}}):
            self.assertEqual(gate.run_chaos()['totals'],{'passed':gate.TOTAL_ROWS,'failed':0})
        with patch.object(chaos,'replay_matrix',return_value={'rows':[],'totals':{'passed':gate.TOTAL_ROWS-1,'failed':1}}):
            with self.assertRaises(AssertionError):gate.run_chaos()
        self.assertEqual(gate.scenario_counts(full_report()),
                         {name:{'passed':number,'failed':0} for name,number in COUNTS.items()})

    def probe_report(self):
        ids=list(gate.REQUIRED_PROBE_IDS)
        return {'successful':True,'tests_run':len(ids),'discovered':list(ids),
                'passed':list(ids),'failed':[],'skipped':[]}

    def test_missing_probe_or_failed_suite_cannot_certify(self):
        proof=gate.validate_probe_reports(self.probe_report())
        self.assertEqual(proof['passed_probes'],sorted(gate.REQUIRED_PROBE_IDS))
        evaluator=gate.EVALUATOR_PROBE_IDS[-1];contract=gate.CONTRACT_PROBE_IDS[0]
        for mutate in [lambda r:r.update(successful=False),
                       lambda r:r.update(tests_run=0),
                       lambda r:r.update(failed=[evaluator]),
                       lambda r:r.update(skipped=[contract]),
                       lambda r:r.update(discovered=r['discovered'][:-1]),
                       lambda r:r.update(passed=[i for i in r['passed'] if i!=evaluator]),
                       lambda r:r.update(passed=[i for i in r['passed'] if i!=contract]),
                       lambda r:r.update(discovered=['unittest.loader._FailedTest.test_m6_evaluation'])]:
            report=self.probe_report();mutate(report)
            with self.assertRaises(ValueError):gate.validate_probe_reports(report)

    def evidence(self,revision='start'):
        return {'schema_version':'1.0','milestone':'m6','status':'PASSED','revision':revision,
                'command':'python scripts/verify_m6.py',
                'evaluation_report':{'totals':{'passed':gate.TOTAL_CASES,'failed':0},
                                     'per_scenario':gate.scenario_counts(full_report())},
                'chaos_report':{'totals':{'passed':gate.TOTAL_ROWS,'failed':0},'rows':gate.TOTAL_ROWS},
                'probe_reports':gate.validate_probe_reports(self.probe_report())}

    def _publish_contexts(self,target,clean=True,lower=None,head='start'):
        return [patch.object(gate,'EVIDENCE_PATH',target),
                patch.object(gate,'validate_lower_evidence') if lower is None
                else patch.object(gate,'validate_lower_evidence',side_effect=RuntimeError(lower)),
                patch.object(gate,'assert_clean_worktree') if clean
                else patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')),
                patch.object(gate,'_revision',return_value=head)]

    def attempt_publication(self,mutate=None,revision='start',starting='start',
                            clean=True,lower=None,head=None,expect=True):
        evidence=self.evidence(revision)
        if mutate is not None:mutate(evidence)
        target=self.root/f'publish-{next(self.counter)}.json'
        contexts=self._publish_contexts(target,clean=clean,lower=lower,head=head or starting)
        with contextlib.ExitStack() as stack:
            for context in contexts:stack.enter_context(context)
            if expect:
                gate.publish_evidence(evidence,starting)
            else:
                with self.assertRaises(RuntimeError):gate.publish_evidence(evidence,starting)
        return target

    def test_tampered_reports_cannot_publish_passed_evidence(self):
        self.assertTrue(self.attempt_publication().exists())
        def refused(mutate,starting='start',clean=True,lower=None,head=None):
            target=self.attempt_publication(mutate,starting=starting,clean=clean,
                                            lower=lower,head=head,expect=False)
            self.assertFalse(target.exists())
        refused(lambda e:e['evaluation_report']['totals'].update(passed=37,failed=1))
        refused(lambda e:e['evaluation_report']['totals'].update(passed=39,failed=0))
        refused(lambda e:e['evaluation_report'].pop('totals'))
        refused(lambda e:e['evaluation_report']['per_scenario'].pop('order-closure'))
        refused(lambda e:e['evaluation_report']['per_scenario']['order-brief'].update(passed=5,failed=1))
        refused(lambda e:e['chaos_report']['totals'].update(passed=20,failed=1))
        refused(lambda e:e['chaos_report'].pop('totals'))
        refused(lambda e:e['probe_reports'].update(passed_probes=[]))
        refused(lambda e:e['probe_reports'].update(passed_probes=e['probe_reports']['passed_probes'][:-1]))
        refused(lambda e:e.pop('evaluation_report'))
        refused(lambda e:e.pop('chaos_report'))
        refused(lambda e:e.pop('probe_reports'))

    def test_publication_checks_survive_optimization(self):
        self.assertTrue(self.attempt_publication().exists())
        def refused(**options):self.attempt_publication(expect=False,**options)
        refused(head='changed')            # HEAD moved during verification
        refused(clean=False)               # dirty worktree
        refused(lower='wrong lower revision')  # stale/failed lower evidence
        refused(starting='other',head='other')  # evidence identity mismatch

    def test_stale_output_removed_before_first_gate_command(self):
        from scripts import verify_m6 as authority
        output=self.root/'m6';output.mkdir()
        stale=output/'verification-evidence.json';stale.write_text('old')
        def stop(*args,**kwargs):
            self.assertFalse(stale.exists())
            raise RuntimeError('lower chain failed')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'run_cli',side_effect=stop), \
             patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='start'):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse(stale.exists())

    def test_stale_output_removed_for_dirty_preflight(self):
        from scripts import verify_m6 as authority
        output=self.root/'m6';output.mkdir()
        stale=output/'verification-evidence.json';stale.write_text('{"status":"PASSED"}')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse(stale.exists())

    def test_evidence_clear_rejects_symlink_redirect(self):
        root=self.root
        for placement in ('leaf','parent'):
            with self.subTest(placement=placement):
                external=root/placement/'outside'/'m6'
                external.mkdir(parents=True)
                marker=external/'important.txt';marker.write_text('preserve',encoding='utf-8')
                workspace=root/placement/'workspace';workspace.mkdir(parents=True)
                output=workspace/'.boundrelay'/'m6'
                if placement=='leaf':
                    output.parent.mkdir();link=output;destination=external
                else:
                    link=output.parent;destination=external.parent
                try:link.symlink_to(destination,target_is_directory=True)
                except (OSError,NotImplementedError):self.skipTest('Directory symlinks are unavailable')
                with patch.object(gate,'OUTPUT_ROOT',output):
                    with self.assertRaises(RuntimeError):gate.clear_previous_evidence()
                self.assertTrue(marker.exists())

    def test_symlinked_temporary_root_is_canonicalized(self):
        from types import SimpleNamespace
        resolved=self.root
        alias=resolved/'temp-alias'
        try:alias.symlink_to(resolved,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('Directory symlinks are unavailable')
        nested=M6VerificationSafetyTests('test_stale_output_removed_before_first_gate_command')
        fake=SimpleNamespace(name=str(alias),cleanup=lambda: None)
        with patch.object(tempfile,'TemporaryDirectory',return_value=fake):nested.setUp()
        try:
            self.assertEqual(Path(nested.path).parent,resolved)
            nested.test_stale_output_removed_before_first_gate_command()
        finally:nested.doCleanups()

    def test_python_suite_sets_and_restores_child_import_path(self):
        from scripts import verify_m6 as authority
        class ChildImportTest(unittest.TestCase):
            def runTest(self):
                subprocess.run([sys.executable,'-c','import boundrelay_m5'],
                               cwd=ROOT,capture_output=True,check=True)
        with patch.dict(os.environ,{},clear=True), \
             patch.object(unittest.TestLoader,'discover',
                          return_value=unittest.TestSuite([ChildImportTest()])):
            report=authority.run_python_suite()
            self.assertTrue(report['successful'])
            self.assertNotIn('PYTHONPATH',os.environ)


if __name__=='__main__':unittest.main()
