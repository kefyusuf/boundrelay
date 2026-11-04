import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'lessons/05-side-effects-approval/python/src'))
from boundrelay_m5.executor import CrashSignal
from boundrelay_m5.runner import run_case
from boundrelay_m5.scenario import load_scenario
from boundrelay_m5.state_store import load_run_state,load_run_state_document
from boundrelay_m5.types import StateBinding
from tools.parity import verify_m5 as gate
from tools.parity.normalize import read_jsonl

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

def crash():
    raise CrashSignal('crash')

def redigest(document):
    from boundrelay_m5.schemas import canonical_state_body,state_digest as digest_of
    document['digest']=digest_of(canonical_state_body(document));return document

def resequenced(events):
    for position,event in enumerate(events,1):event['sequence']=position;event['event_id']=f'event-{position}'
    return events

def phase(kind,crash,trace,state_dir,result,state):
    return {'kind':kind,'crash':crash,'exit_code':2 if crash else 0,'result':result,'events':read_jsonl(trace),
            'trace_path':trace,'state_dir':state_dir,'state':state,
            'ledger':gate.read_ledger(state_dir),'audit':gate.read_audit(state_dir)}

class M5VerificationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.path=str(self.root/'trace.jsonl')

    def _case(self,case_id):
        return asdict(next(c for c in load_scenario().cases if c.case_id==case_id))

    def simple_flow(self,case_id):
        state_dir=str(self.root/case_id);trace=str(self.root/(case_id+'.jsonl'))
        result=asyncio.run(run_case(case_id=case_id,trace_path=trace,state_dir=state_dir))
        state=load_run_state_document(Path(state_dir)/result['run_id']/'state.json',binding(case_id))
        return {'case_id':case_id,'case':self._case(case_id),'phases':[phase('fresh',None,trace,state_dir,result,state)]}

    def crash_resume_flow(self,case_id):
        state_dir=str(self.root/case_id);p1=str(self.root/(case_id+'.p1.jsonl'));p2=str(self.root/(case_id+'.p2.jsonl'))
        with self.assertRaises(CrashSignal):asyncio.run(run_case(case_id=case_id,trace_path=p1,state_dir=state_dir,on_crash=crash))
        crash_state=load_run_state(state_dir,binding(case_id))['document']
        crash_phase=phase('fresh','before_submit' if case_id=='retry-before-submit' else 'in_submit_window',p1,state_dir,None,crash_state)
        result=asyncio.run(run_case(case_id=case_id,trace_path=p2,state_dir=state_dir,resume=True))
        final=load_run_state_document(Path(state_dir)/result['run_id']/'state.json',binding(case_id))
        return {'case_id':case_id,'case':self._case(case_id),'phases':[
            crash_phase,phase('resume',None,p2,state_dir,result,final)]}

    def duplicate_flow(self):
        state_dir=str(self.root/'duplicate-key-suppressed');t1=str(self.root/'duplicate-key-suppressed.r1.jsonl');t2=str(self.root/'duplicate-key-suppressed.r2.jsonl')
        one=asyncio.run(run_case(case_id='duplicate-key-suppressed',trace_path=t1,state_dir=state_dir))
        first=load_run_state_document(Path(state_dir)/one['run_id']/'state.json',binding('duplicate-key-suppressed'))
        first_phase=phase('fresh',None,t1,state_dir,one,first)
        two=asyncio.run(run_case(case_id='duplicate-key-suppressed',trace_path=t2,state_dir=state_dir))
        second=load_run_state_document(Path(state_dir)/two['run_id']/'state.json',binding('duplicate-key-suppressed'))
        return {'case_id':'duplicate-key-suppressed','case':self._case('duplicate-key-suppressed'),'phases':[
            first_phase,phase('duplicate',None,t2,state_dir,two,second)]}

    def all_flows(self):
        flows={'approval-granted-effect-once':self.simple_flow('approval-granted-effect-once'),
               'approval-rejected-no-effect':self.simple_flow('approval-rejected-no-effect'),
               'retry-before-submit':self.crash_resume_flow('retry-before-submit'),
               'crash-submit-window-resolved':self.crash_resume_flow('crash-submit-window-resolved'),
               'sink-unavailable-unknown':self.crash_resume_flow('sink-unavailable-unknown'),
               'duplicate-key-suppressed':self.duplicate_flow()}
        for flow in flows.values():gate.assert_flow_behavior(flow,'python')
        return flows

    def mutate(self,target,apply):
        copied=deepcopy(target);apply(copied)
        with self.subTest(apply=apply):
            with self.assertRaises((AssertionError,ValueError)):gate.semantic_flow(copied,'python')

    def test_raw_mutations_fail_before_projection(self):
        flows=self.all_flows()
        granted=flows['approval-granted-effect-once'];rejected=flows['approval-rejected-no-effect']
        retry=flows['retry-before-submit'];resolved=flows['crash-submit-window-resolved']
        unknown=flows['sink-unavailable-unknown'];dup=flows['duplicate-key-suppressed']
        def drop_event(event_type):
            def apply(target):
                events=[event for event in target['phases'][0]['events'] if event['type']!=event_type]
                target['phases'][0]['events']=resequenced(events)
            return apply
        self.mutate(granted,drop_event('approval.granted'))
        self.mutate(granted,drop_event('approval.requested'))
        def stale_digest(target):
            for event in target['phases'][0]['events']:
                if event['type']=='approval.requested':event['data']['payload_digest']='f'*64
        self.mutate(granted,stale_digest)
        self.mutate(granted,lambda t:t['phases'][0]['ledger'].append(dict(t['phases'][0]['ledger'][0])))
        self.mutate(granted,lambda t:t['phases'][0]['ledger'][0].update(key='other-key'))
        def reorder_audit(target):
            target['phases'][0]['audit']=list(reversed(target['phases'][0]['audit']))
        self.mutate(granted,reorder_audit)
        self.mutate(granted,lambda t:t['phases'][0]['result']['worker_outcomes'][0]['output'].update(order_status='CANCELLED'))
        def tamper_checkpoint(target):
            for event in target['phases'][0]['events']:
                if event['type']=='checkpoint.saved':event['data']['sequence_cursor']=99
        self.mutate(granted,tamper_checkpoint)
        self.mutate(dup,lambda t:[event for event in t['phases'][1]['events'] if event['type']=='tool.completed'][0].update(duplicate=False))
        self.mutate(rejected,lambda t:t['phases'][0]['audit'].append(dict(t['phases'][0]['audit'][0],kind='effect',decision=None)))

        def flatten_state(target):
            document=deepcopy(target['phases'][1]['state']);document['status']='SUCCEEDED'
            target['phases'][1]['state']=redigest(document)
        self.mutate(unknown,flatten_state)
        def flatten_terminal(target):
            events=target['phases'][1]['events'];events[-1]['data']['status']='SUCCEEDED'
            target['phases'][1]['events']=resequenced(events)
        self.mutate(unknown,flatten_terminal)
        self.mutate(unknown,lambda t:t['phases'][1]['result'].update(status='SUCCEEDED',run_state_status='SUCCEEDED',effect_status='EFFECT_COMPLETED'))
        def resubmit_landed(target):
            document=deepcopy(target['phases'][1]['state']);document['effect']['duplicate']=True
            target['phases'][1]['state']=redigest(document)
            target['phases'][1]['result']['reconciled']=False
        self.mutate(resolved,resubmit_landed)
        self.mutate(resolved,lambda t:t['phases'][1]['result'].update(reconciled=False))
        def drop_marker(target):
            document=deepcopy(target['phases'][0]['state']);document['submit_marker']=None
            target['phases'][0]['state']=redigest(document)
        self.mutate(resolved,drop_marker)
        def add_marker(target):
            from boundrelay_m5.idempotency import effect_digest,effect_key
            from boundrelay_m5.schemas import canonical_state_body
            payload={'operation':'cancel-and-refund','order_id':'ORD-1001','refund_amount_cents':4200,'currency':'EUR'}
            document=deepcopy(target['phases'][0]['state'])
            document['submit_marker']={'key':effect_key(payload),'payload_digest':effect_digest(payload)}
            target['phases'][0]['state']=redigest(document)
        self.mutate(rejected,add_marker)
        def add_effect_to_crash(target):
            document=deepcopy(target['phases'][0]['state'])
            document['effect']=dict(document['submit_marker'],status='EFFECT_COMPLETED',outcome={'refund_id':'RFL-1001','refunded_at':'2026-11-02T00:00:00Z'},duplicate=False)
            target['phases'][0]['state']=redigest(document)
        self.mutate(resolved,add_effect_to_crash)
        self.mutate(retry,lambda t:t['phases'][0].update(exit_code=0))
        self.mutate(retry,lambda t:t['phases'][0].update(result={'schema_version':'1.0'}))
        def crash_terminal(target):
            events=target['phases'][0]['events'];terminal=deepcopy(events[-1])
            terminal['type']='run.completed';terminal['data']={'status':'RUNNING'}
            target['phases'][0]['events']=resequenced(events+[terminal])
        self.mutate(retry,crash_terminal)
        def duplicate_terminal(target):
            events=target['phases'][1]['events'];events.append(deepcopy(events[-1]))
            target['phases'][1]['events']=resequenced(events)
        self.mutate(retry,duplicate_terminal)
        self.mutate(retry,lambda t:t['phases'][1]['result'].update(run_id='other-run'))

        path=Path(retry['phases'][1]['trace_path'])
        for content in ['\n','{not json}\n',json.dumps(retry['phases'][1]['events'][0])+'\n\n','{"value":NaN}\n']:
            Path(path).write_text(content,encoding='utf-8')
            with self.assertRaises(ValueError):read_jsonl(path)

    def reports(self):
        executor=gate.EXECUTOR_PROBES;recovery=gate.RECOVERY_PROBES
        ts={'success':True,'numTotalTests':len(executor)+len(recovery),'numPassedTests':len(executor)+len(recovery),
            'numFailedTests':0,'numFailedTestSuites':0,'testResults':[
            {'name':'test/executor.test.ts','status':'passed','assertionResults':[
                {'title':name,'fullName':name,'status':'passed'} for name in executor]},
            {'name':'test/recovery.test.ts','status':'passed','assertionResults':[
                {'title':name,'fullName':name,'status':'passed'} for name in recovery]}]}
        ids=[f'test_executor.ExecutorTests.test_{name}' for name in executor]+[f'test_recovery.RecoveryTests.test_{name}' for name in recovery]
        py={'successful':True,'tests_run':len(ids),'discovered':ids,'passed':ids,'failed':[],'skipped':[]}
        return ts,py

    def test_missing_probe_or_zero_suite_cannot_certify(self):
        ts,py=self.reports();gate.validate_probe_reports(ts,py)
        for mutate in [lambda t,p:t.update(numPassedTests=0),
                       lambda t,p:t['testResults'][0]['assertionResults'].pop(),
                       lambda t,p:t['testResults'][0]['assertionResults'][0].update(status='skipped'),
                       lambda t,p:t['testResults'][1].update(name='test/unknown.test.ts'),
                       lambda t,p:t['testResults'][1]['assertionResults'][0].update(status='failed'),
                       lambda t,p:p.update(tests_run=0),
                       lambda t,p:p.update(passed=p['passed'][1:]),
                       lambda t,p:p.update(discovered=['unittest.loader._FailedTest.test_executor']),
                       lambda t,p:p.update(successful=False),
                       lambda t,p:p.update(skipped=p['passed'][:1])]:
            t,p=deepcopy(ts),deepcopy(py);mutate(t,p)
            with self.assertRaises((RuntimeError,ValueError)):gate.validate_probe_reports(t,p)

    def test_publication_checks_survive_optimization(self):
        path=self.root/'evidence.json'
        with patch.object(gate,'EVIDENCE_PATH',path),patch.object(gate,'validate_lower_evidence'),patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='changed'):
            with self.assertRaises(RuntimeError):gate.publish_evidence({'status':'PASSED','revision':'start'},'start')
            self.assertFalse(path.exists())
        with patch.object(gate,'EVIDENCE_PATH',path),patch.object(gate,'validate_lower_evidence'),patch.object(gate,'_revision',return_value='start'),patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')):
            with self.assertRaises(RuntimeError):gate.publish_evidence({'status':'PASSED','revision':'start'},'start')
            self.assertFalse(path.exists())
        with patch.object(gate,'EVIDENCE_PATH',path),patch.object(gate,'validate_lower_evidence',side_effect=RuntimeError('wrong lower revision')),patch.object(gate,'_revision',return_value='start'),patch.object(gate,'assert_clean_worktree'):
            with self.assertRaises(RuntimeError):gate.publish_evidence({'status':'PASSED','revision':'start'},'start')
            self.assertFalse(path.exists())
        with patch.object(gate,'EVIDENCE_PATH',path),patch.object(gate,'validate_lower_evidence'),patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='start'):
            with self.assertRaises(RuntimeError):gate.publish_evidence({'status':'PASSED','revision':'start','extra':'x'},'other')
            self.assertFalse(path.exists())

    def test_stale_output_removed_before_first_gate_command(self):
        from scripts import verify_m5 as authority
        output=self.root/'m5';output.mkdir();(output/'verification-evidence.json').write_text('old')
        def stop(*args,**kwargs):
            self.assertFalse((output/'verification-evidence.json').exists())
            raise RuntimeError('lower chain failed')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='start'),patch.object(authority,'run',side_effect=stop):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse((output/'verification-evidence.json').exists())

    def test_python_suite_sets_and_restores_child_import_path(self):
        from scripts import verify_m5 as authority
        class ChildImportTest(unittest.TestCase):
            def runTest(self):
                subprocess.run([sys.executable,'-c','import boundrelay_m5'],cwd=ROOT,capture_output=True,check=True)
        import os
        with patch.dict(os.environ,{},clear=True),patch.object(unittest.TestLoader,'discover',return_value=unittest.TestSuite([ChildImportTest()])):
            report=authority.run_python_suite()
            self.assertTrue(report['successful'])
            self.assertNotIn('PYTHONPATH',os.environ)

    def test_stale_output_removed_for_dirty_preflight(self):
        from scripts import verify_m5 as authority
        output=self.root/'m5';output.mkdir()
        stale=output/'verification-evidence.json';stale.write_text('{"status":"PASSED"}')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse(stale.exists())

    def test_evidence_clear_rejects_symlink_redirect(self):
        root=self.root
        for placement in ('leaf','parent'):
            with self.subTest(placement=placement):
                external=root/placement/'outside'/'m5'
                external.mkdir(parents=True)
                marker=external/'important.txt';marker.write_text('preserve',encoding='utf-8')
                workspace=root/placement/'workspace';workspace.mkdir(parents=True)
                output=workspace/'.boundrelay'/'m5'
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
        nested=M5VerificationSafetyTests('test_stale_output_removed_before_first_gate_command')
        fake=SimpleNamespace(name=str(alias),cleanup=lambda: None)
        with patch.object(tempfile,'TemporaryDirectory',return_value=fake):nested.setUp()
        try:
            self.assertEqual(Path(nested.path).parent,resolved)
            nested.test_stale_output_removed_before_first_gate_command()
        finally:nested.doCleanups()


if __name__=='__main__':unittest.main()
