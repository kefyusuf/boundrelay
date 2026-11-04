"""M7 verifier-safety suite: mutations that must fail before M7 evidence is
published — projection drift, three-language golden divergence, Go gate
failures, missing Go proofs, tampered reports, moved HEAD, dirty trees —
mirroring the M6 suite. All heavy boundaries are faked; the suite stays fast
and scripts/verify_m7.py performs the real runs."""
from copy import deepcopy
import contextlib
import json
import os
from pathlib import Path
import shutil
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
from tools.parity import verify_m7 as gate
from tools.parity.test_m6_evaluation import canned_flow

SCENARIO='support-triage';CASE_KEY='billing-duplicate-charge@model'
COUNTS={'support-triage':7,'order-investigation':8,'support-handoff':5,
        'order-brief':6,'order-brief-recovery':6,'order-closure':6}
THREE_LANGUAGE={'support-triage','order-brief'}

def full_report():
    cases=[{'scenario_id':name,'case_key':f'{name}-{index}','status':'PASS',
            'languages':['typescript','python','go'] if name in THREE_LANGUAGE
            else ['typescript','python']}
           for name,number in COUNTS.items() for index in range(number)]
    return {'totals':{'passed':gate.TOTAL_CASES,'failed':0},'cases':cases}

def go_flows_report():
    return {'totals':{'passed':gate.THREE_LANGUAGE_CASES,'failed':0}}

def probe_report():
    ids=list(gate.REQUIRED_PROBE_IDS)
    return {'successful':True,'tests_run':len(ids),'discovered':list(ids),
            'passed':list(ids),'failed':[],'skipped':[]}

class M7VerificationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.path=str(self.root/'trace.jsonl')
        self.counter=count()

    def projection_root(self):
        """A disposable copy of the real fixture tree so projection drift can
        be fabricated without dirtying the worktree."""
        temp=self.root/f'fixtures-{next(self.counter)}'
        shutil.copytree(ROOT/'fixtures',temp/'fixtures')
        return temp

    def test_validate_projections_accepts_honest_copies(self):
        with patch.object(gate,'ROOT',self.projection_root()):
            proof=gate.validate_projections()
        self.assertEqual(proof['status'],'matched')

    def test_projection_drift_blocks_certification(self):
        mutations={
            'scenario':('fixtures/goprojections/support-triage/scenario.json',
                        lambda d:d.update(routes=['billing'])),
            'attribution':('fixtures/goprojections/order-brief/attribution.json',
                           lambda d:d['latency_ms'].update(synthesize=99)),
            'workers':('fixtures/goprojections/order-brief/workers.json',
                       lambda d:d['fixtures/workers/order-brief/complete.yaml']
                                ['order-details'].update(operation='raise')),
            'worker-set':('fixtures/goprojections/order-brief/workers.json',
                          lambda d:d.pop('fixtures/workers/order-brief/all-failed.yaml'))}
        for name,(relative,mutate) in mutations.items():
            with self.subTest(name=name):
                temp=self.projection_root()
                with patch.object(gate,'ROOT',temp):
                    gate.validate_projections()
                    path=temp/relative
                    document=json.loads(path.read_text(encoding='utf-8'))
                    mutate(document)
                    path.write_text(json.dumps(document),encoding='utf-8')
                    with self.assertRaises(RuntimeError):gate.validate_projections()

    def test_three_language_golden_divergence_blocks(self):
        diverged=deepcopy(M7VerificationSafetyTests.diverged_flow())
        with self.assertRaises(ev.ToolingError) as caught:
            ev.flow_evidence(canned_flow(
                languages=['typescript','python','go'],go_result=diverged['go_result']))
        self.assertIn('typescript and go',str(caught.exception))
        diverged_events=deepcopy(canned_flow()['go_events'])
        diverged_events[2]['data']={'step_name':'worker.order-details'}
        with self.assertRaises(ev.ToolingError):
            ev.flow_evidence(canned_flow(
                languages=['typescript','python','go'],go_events=diverged_events))

    @staticmethod
    def diverged_flow():
        flow=canned_flow(languages=['typescript','python','go'])
        flow['go_result']=deepcopy(flow['go_result'])
        flow['go_result']['status']='FAILED'
        return flow

    def fake_go_process(self,fmt_drift=False,vet_code=0,test_code=0):
        def process(command,cwd=None,text=None,capture_output=None):
            parts=[str(part) for part in command]
            code,stdout=0,''
            if any(part.endswith('vet') for part in parts[:3]):code=vet_code
            elif any(part.endswith('test') for part in parts[:3]):code=test_code
            elif any(part.endswith('-l') for part in parts[:3]) and fmt_drift:
                stdout='internal/m0/x.go\n'
            return type('Completed',(),{'returncode':code,'stdout':stdout,'stderr':'boom' if code else ''})()
        return process

    @staticmethod
    def fake_evaluate(scenarios=None,report_path=None,only_case=None,
                      languages=ev.DEFAULT_LANGUAGES):
        if scenarios and set(scenarios)==set(ev.GO_SCENARIOS):
            report=full_report()
            report['cases']=[case for case in report['cases']
                             if case['scenario_id'] in ev.GO_SCENARIOS]
            report['totals']={'passed':len(report['cases']),'failed':0}
            return report
        return full_report()

    def test_go_gate_failures_block_certification(self):
        with patch.object(gate.subprocess,'run',side_effect=self.fake_go_process()):
            self.assertEqual(gate.run_go_gates(),{'vet':'clean','test':'ok','gofmt':'clean'})
        for kwargs in ({'vet_code':1},{'test_code':2},{'fmt_drift':True}):
            with self.subTest(**kwargs):
                with patch.object(gate.subprocess,'run',
                                  side_effect=self.fake_go_process(**kwargs)):
                    with self.assertRaises(RuntimeError):gate.run_go_gates()

    def test_gate_helpers_reject_incomplete_reports(self):
        with patch.object(ev,'evaluate',side_effect=self.fake_evaluate):
            self.assertEqual(gate.run_evaluator()['totals'],{'passed':38,'failed':0})
            self.assertEqual(gate.run_go_flows()['totals'],{'passed':13,'failed':0})
        for totals in ({'passed':37,'failed':1},{'passed':39,'failed':0}):
            with patch.object(ev,'evaluate',return_value={'totals':totals,'cases':[]}):
                with self.assertRaises(AssertionError):gate.run_evaluator()
        short=full_report();short['cases']=short['cases'][:-1]
        with patch.object(ev,'evaluate',return_value=short):
            with self.assertRaises(AssertionError):gate.run_evaluator()
        two_language=full_report()
        for case in two_language['cases']:
            case['languages']=['typescript','python']
        with patch.object(ev,'evaluate',return_value=two_language):
            with self.assertRaises(AssertionError):gate.run_evaluator()
        with patch.object(ev,'evaluate',return_value=two_language):
            with self.assertRaises(AssertionError):gate.run_go_flows()
        rows=[{'failure_id':f'M0-F{index}'} for index in range(gate.TOTAL_ROWS)]
        with patch.object(chaos,'replay_matrix',return_value={'rows':rows,'totals':{'passed':gate.TOTAL_ROWS,'failed':0}}):
            self.assertEqual(gate.run_chaos()['totals'],{'passed':gate.TOTAL_ROWS,'failed':0})
        with patch.object(chaos,'replay_matrix',return_value={'rows':[],'totals':{'passed':gate.TOTAL_ROWS-1,'failed':1}}):
            with self.assertRaises(AssertionError):gate.run_chaos()
        self.assertEqual(gate.scenario_counts(full_report()),
                         {name:{'passed':number,'failed':0} for name,number in COUNTS.items()})

    def test_missing_probe_or_failed_suite_cannot_certify(self):
        proof=gate.validate_probe_reports(probe_report())
        self.assertEqual(proof['passed_probes'],sorted(gate.REQUIRED_PROBE_IDS))
        language=gate.M7_LANGUAGE_PROBE_IDS[0];contract=gate.M7_CONTRACT_PROBE_IDS[0]
        for mutate in [lambda r:r.update(successful=False),
                       lambda r:r.update(tests_run=0),
                       lambda r:r.update(failed=[language]),
                       lambda r:r.update(skipped=[contract]),
                       lambda r:r.update(discovered=r['discovered'][:-1]),
                       lambda r:r.update(passed=[i for i in r['passed'] if i!=language]),
                       lambda r:r.update(passed=[i for i in r['passed'] if i!=contract]),
                       lambda r:r.update(discovered=['unittest.loader._FailedTest.test_m7_contracts'])]:
            report=probe_report();mutate(report)
            with self.assertRaises(ValueError):gate.validate_probe_reports(report)

    def evidence(self,revision='start'):
        return {'schema_version':'1.0','milestone':'m7','status':'PASSED','revision':revision,
                'command':'python scripts/verify_m7.py',
                'projections':{'scenarios':['support-triage','order-brief'],'status':'matched'},
                'go_gates':{'vet':'clean','test':'ok','gofmt':'clean'},
                'go_flows':{'totals':{'passed':gate.THREE_LANGUAGE_CASES,'failed':0}},
                'evaluation_report':{'totals':{'passed':gate.TOTAL_CASES,'failed':0},
                                     'per_scenario':gate.scenario_counts(full_report()),
                                     'three_language_cases':gate.THREE_LANGUAGE_CASES},
                'chaos_report':{'totals':{'passed':gate.TOTAL_ROWS,'failed':0},'rows':gate.TOTAL_ROWS},
                'probe_reports':gate.validate_probe_reports(probe_report())}

    def _publish_contexts(self,target,clean=True,lower=None,head='start',
                          projections=None):
        return [patch.object(gate,'EVIDENCE_PATH',target),
                patch.object(gate,'validate_lower_evidence') if lower is None
                else patch.object(gate,'validate_lower_evidence',side_effect=RuntimeError(lower)),
                patch.object(gate,'assert_clean_worktree') if clean
                else patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')),
                patch.object(gate,'_revision',return_value=head),
                patch.object(gate,'validate_projections') if projections is None
                else patch.object(gate,'validate_projections',side_effect=RuntimeError(projections))]

    def attempt_publication(self,mutate=None,revision='start',starting='start',
                            clean=True,lower=None,head=None,projections=None,expect=True):
        evidence=self.evidence(revision)
        if mutate is not None:mutate(evidence)
        target=self.root/f'publish-{next(self.counter)}.json'
        contexts=self._publish_contexts(target,clean=clean,lower=lower,head=head or starting,
                                        projections=projections)
        with contextlib.ExitStack() as stack:
            for context in contexts:stack.enter_context(context)
            if expect:
                gate.publish_evidence(evidence,starting)
            else:
                with self.assertRaises(RuntimeError):gate.publish_evidence(evidence,starting)
        return target

    def test_tampered_reports_cannot_publish_passed_evidence(self):
        self.assertTrue(self.attempt_publication().exists())
        def refused(mutate=None,**options):
            target=self.attempt_publication(mutate,expect=False,**options)
            self.assertFalse(target.exists())
        refused(mutate=lambda e:e['evaluation_report']['totals'].update(passed=37,failed=1))
        refused(mutate=lambda e:e['evaluation_report']['totals'].update(passed=39,failed=0))
        refused(mutate=lambda e:e['evaluation_report'].pop('totals'))
        refused(mutate=lambda e:e['evaluation_report'].pop('per_scenario'))
        refused(mutate=lambda e:e['evaluation_report']['per_scenario'].pop('order-closure'))
        refused(mutate=lambda e:e['evaluation_report']['per_scenario']['order-brief'].update(passed=5,failed=1))
        refused(mutate=lambda e:e['evaluation_report'].update(three_language_cases=12))
        refused(mutate=lambda e:e['evaluation_report'].pop('three_language_cases'))
        refused(mutate=lambda e:e['go_flows']['totals'].update(passed=12,failed=1))
        refused(mutate=lambda e:e.pop('go_flows'))
        refused(mutate=lambda e:e['chaos_report']['totals'].update(passed=20,failed=1))
        refused(mutate=lambda e:e.pop('chaos_report'))
        refused(mutate=lambda e:e['go_gates'].update(test='failed'))
        refused(mutate=lambda e:e['go_gates'].pop('gofmt'))
        refused(mutate=lambda e:e.pop('go_gates'))
        refused(mutate=lambda e:e['probe_reports'].update(passed_probes=[]))
        refused(mutate=lambda e:e['probe_reports'].update(
            passed_probes=e['probe_reports']['passed_probes'][:-1]))
        refused(mutate=lambda e:e.pop('probe_reports'))
        refused(mutate=lambda e:e.pop('projections'))
        refused(projections='projections drifted')

    def test_publication_checks_survive_optimization(self):
        self.assertTrue(self.attempt_publication().exists())
        def refused(**options):self.attempt_publication(expect=False,**options)
        refused(head='changed')            # HEAD moved during verification
        refused(clean=False)               # dirty worktree
        refused(lower='wrong lower revision')  # stale/failed lower evidence
        refused(starting='other',head='other')  # evidence identity mismatch
        refused(projections='drift')       # Go projection drift blocks publication

    def test_lower_evidence_must_be_m6_passed_on_revision(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            evidence=Path(directory)/'.boundrelay/m6/verification-evidence.json'
            evidence.parent.mkdir(parents=True)
            with patch.object(gate,'ROOT',Path(directory)):
                def attempt(document):
                    evidence.write_text(json.dumps(document),encoding='utf-8')
                    gate.validate_lower_evidence('start')
                attempt({'status':'PASSED','revision':'start','milestone':'m6'})
                for mutate in (lambda d:d.update(status='FAILED'),
                               lambda d:d.update(revision='other'),
                               lambda d:d.update(milestone='m5')):
                    document={'status':'PASSED','revision':'start','milestone':'m6'}
                    mutate(document)
                    with self.assertRaises(RuntimeError):attempt(document)
                evidence.unlink()
                with self.assertRaises(RuntimeError):gate.validate_lower_evidence('start')

    def test_stale_output_removed_before_first_gate_command(self):
        from scripts import verify_m7 as authority
        output=self.root/'m7';output.mkdir()
        stale=output/'verification-evidence.json';stale.write_text('old')
        def stop(*args,**kwargs):
            self.assertFalse(stale.exists())
            raise RuntimeError('lower chain failed')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'run_cli',side_effect=stop), \
             patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='start'):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse(stale.exists())

    def test_stale_output_removed_for_dirty_preflight(self):
        from scripts import verify_m7 as authority
        output=self.root/'m7';output.mkdir()
        stale=output/'verification-evidence.json';stale.write_text('{"status":"PASSED"}')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse(stale.exists())

    def test_evidence_clear_rejects_symlink_redirect(self):
        root=self.root
        for placement in ('leaf','parent'):
            with self.subTest(placement=placement):
                external=root/placement/'outside'/'m7'
                external.mkdir(parents=True)
                marker=external/'important.txt';marker.write_text('preserve',encoding='utf-8')
                workspace=root/placement/'workspace';workspace.mkdir(parents=True)
                output=workspace/'.boundrelay'/'m7'
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
        nested=M7VerificationSafetyTests('test_stale_output_removed_before_first_gate_command')
        fake=SimpleNamespace(name=str(alias),cleanup=lambda: None)
        with patch.object(tempfile,'TemporaryDirectory',return_value=fake):nested.setUp()
        try:
            self.assertEqual(Path(nested.path).parent,resolved)
            nested.test_stale_output_removed_before_first_gate_command()
        finally:nested.doCleanups()

    def test_python_suite_sets_and_restores_child_import_path(self):
        from scripts import verify_m7 as authority
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

