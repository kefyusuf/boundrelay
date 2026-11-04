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
sys.path.insert(0,str(ROOT/'lessons/04-durable-state-recovery/python/src'))
from boundrelay_m4.executor import CrashSignal
from boundrelay_m4.runner import run_case
from boundrelay_m4.scenario import load_scenario
from boundrelay_m4.state_store import load_run_state,load_run_state_document
from boundrelay_m4.types import StateBinding
from tools.parity import verify_m4 as gate
from tools.parity.normalize import read_jsonl

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

def crash():
    raise CrashSignal('crash')

class M4VerificationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.path=str(self.root/'trace.jsonl')

    def crash_resume_flow(self):
        state_dir=str(self.root/'state');phase1=str(self.root/'phase1.jsonl');phase2=str(self.root/'phase2.jsonl')
        with self.assertRaises(CrashSignal):asyncio.run(run_case(case_id='parallel-crash-resume',trace_path=phase1,state_dir=state_dir,on_crash=crash))
        crash_state=load_run_state(state_dir,binding('parallel-crash-resume'))['document']
        result=asyncio.run(run_case(case_id='parallel-crash-resume',trace_path=phase2,state_dir=state_dir,resume=True))
        final=load_run_state(state_dir,binding('parallel-crash-resume'))['document']
        case=asdict(next(c for c in load_scenario().cases if c.case_id=='parallel-crash-resume'))
        return {'case_id':'parallel-crash-resume','case':case,'phases':[
            {'kind':'fresh','crash':True,'exit_code':2,'result':None,'events':read_jsonl(phase1),'trace_path':phase1,'state':crash_state,'state_dir':state_dir},
            {'kind':'resume','crash':False,'exit_code':0,'result':result,'events':read_jsonl(phase2),'trace_path':phase2,'state':final,'state_dir':state_dir}]}

    def replay_flow(self):
        state_dir=str(self.root/'replay-state');phase1=str(self.root/'replay1.jsonl');phase2=str(self.root/'replay2.jsonl')
        first=asyncio.run(run_case(case_id='parallel-replay-from-checkpoint',trace_path=phase1,state_dir=state_dir))
        source_state=load_run_state(state_dir,binding('parallel-replay-from-checkpoint'))['document']
        source_dir=Path(state_dir)/first['run_id']
        snapshot=load_run_state_document(source_dir/'checkpoints'/'step-1.json',binding('parallel-replay-from-checkpoint'))
        second=asyncio.run(run_case(case_id='parallel-replay-from-checkpoint',trace_path=phase2,state_dir=state_dir,replay_from=str(source_dir/'checkpoints'/'step-1.json')))
        source_after=load_run_state_document(source_dir/'state.json',binding('parallel-replay-from-checkpoint'))
        replay_state=load_run_state_document(Path(state_dir)/second['run_id']/'state.json',binding('parallel-replay-from-checkpoint'))
        case=asdict(next(c for c in load_scenario().cases if c.case_id=='parallel-replay-from-checkpoint'))
        return {'case_id':'parallel-replay-from-checkpoint','case':case,'phases':[
            {'kind':'fresh','crash':False,'exit_code':0,'result':first,'events':read_jsonl(phase1),'trace_path':phase1,'state':source_state,'state_dir':state_dir},
            {'kind':'replay','crash':False,'exit_code':0,'result':second,'events':read_jsonl(phase2),'trace_path':phase2,'state':replay_state,'source_state':source_after,'snapshot':snapshot,'state_dir':state_dir}]}

    def cancel_flow(self):
        state_dir=str(self.root/'cancel-state');phase1=str(self.root/'cancel1.jsonl');phase2=str(self.root/'cancel2.jsonl')
        first=asyncio.run(run_case(case_id='parallel-cancel-resume',trace_path=phase1,state_dir=state_dir))
        cancelled_state=load_run_state(state_dir,binding('parallel-cancel-resume'))['document']
        second=asyncio.run(run_case(case_id='parallel-cancel-resume',trace_path=phase2,state_dir=state_dir,resume=True))
        final=load_run_state(state_dir,binding('parallel-cancel-resume'))['document']
        case=asdict(next(c for c in load_scenario().cases if c.case_id=='parallel-cancel-resume'))
        return {'case_id':'parallel-cancel-resume','case':case,'phases':[
            {'kind':'fresh','crash':False,'exit_code':0,'result':first,'events':read_jsonl(phase1),'trace_path':phase1,'state':cancelled_state,'state_dir':state_dir},
            {'kind':'resume','crash':False,'exit_code':0,'result':second,'events':read_jsonl(phase2),'trace_path':phase2,'state':final,'state_dir':state_dir}]}

    def resequenced(self,events):
        for position,event in enumerate(events,1):event['sequence']=position;event['event_id']=f'event-{position}'
        return events

    def test_raw_mutations_fail_before_projection(self):
        flow=self.crash_resume_flow();gate.assert_flow_behavior(flow,'python')
        cancel=self.cancel_flow();gate.assert_flow_behavior(cancel,'python')
        replay=self.replay_flow();gate.assert_flow_behavior(replay,'python')
        def mutate(target,apply):
            copied=deepcopy(target);apply(copied)
            with self.subTest(apply=apply):
                with self.assertRaises((AssertionError,ValueError)):gate.semantic_flow(copied,'python')
        crash_events=flow['phases'][0]['events']
        saved_positions=[i for i,event in enumerate(crash_events) if event['type']=='checkpoint.saved']
        def duplicate_checkpoint(target):
            events=target['phases'][0]['events'];events.insert(saved_positions[0]+1,deepcopy(events[saved_positions[0]]))
            target['phases'][0]['events']=self.resequenced(events)
        mutate(flow,duplicate_checkpoint)
        def drop_last_checkpoint(target):
            events=[event for index,event in enumerate(target['phases'][0]['events']) if index!=saved_positions[-1]]
            target['phases'][0]['events']=self.resequenced(events)
        mutate(flow,drop_last_checkpoint)
        def restore_after_start(target):
            events=target['phases'][1]['events'];restored=events.pop(2);events.insert(4,restored)
            target['phases'][1]['events']=self.resequenced(events)
        mutate(flow,restore_after_start)
        def reexecute_recorded(target):
            base=next(event for event in target['phases'][0]['events'] if event['type']=='step.started' and event['data']['worker_id']=='order-details')
            terminal=next(event for event in target['phases'][0]['events'] if event['type']=='step.completed' and event['data']['outcome']['worker_id']=='order-details')
            run_id=target['phases'][1]['events'][0]['run_id'];extra=[deepcopy(base),deepcopy(terminal)]
            for event in extra:event['run_id']=run_id
            target['phases'][1]['events']=self.resequenced(target['phases'][1]['events']+extra)
        mutate(flow,reexecute_recorded)
        mutate(flow,lambda target:target['phases'][1]['result']['worker_outcomes'][0]['output'].update(order_status='CANCELLED'))
        mutate(cancel,lambda target:target['phases'][0]['result'].update(failure_code='ALL_WORKERS_FAILED'))
        mutate(flow,lambda target:target['phases'][0].update(exit_code=0))
        mutate(flow,lambda target:target['phases'][0].update(result={'schema_version':'1.0'}))
        def crash_terminal(target):
            events=target['phases'][0]['events'];terminal=deepcopy(events[-1]);terminal['type']='run.completed';terminal['data']={'status':'RUNNING'}
            target['phases'][0]['events']=self.resequenced(events+[terminal])
        mutate(flow,crash_terminal)

        def mutate_source(target):
            from boundrelay_m4.schemas import canonical_state_body,state_digest as digest_of
            document=deepcopy(target['phases'][1]['source_state']);document['status']='RUNNING'
            document['digest']=digest_of(canonical_state_body(document))
            target['phases'][1]['source_state']=document
        mutate(replay,mutate_source)
        mutate(flow,lambda target:target['phases'][1]['state'].update(digest='a'*64))
        def wrong_binding(target):
            from boundrelay_m4.schemas import canonical_state_body,state_digest as digest_of
            document=deepcopy(target['phases'][1]['state']);document['case_id']='parallel-cancel-resume'
            document['digest']=digest_of(canonical_state_body(document))
            target['phases'][1]['state']=document
        mutate(flow,wrong_binding)
        mutate(flow,lambda target:target['phases'][1]['events'][3].update(sequence=99))
        mutate(flow,lambda target:target['phases'][1]['events'][3].update(event_id=target['phases'][1]['events'][2]['event_id']))
        def early_synthesis(target):
            events=target['phases'][1]['events']
            started=next(event for event in events if event['data'].get('step_name')=='synthesize')
            events.remove(started);events.insert(3,started)
            target['phases'][1]['events']=self.resequenced(events)
        mutate(flow,early_synthesis)
        mutate(cancel,lambda target:target['phases'][0]['result'].update(peak_concurrency=1))
        mutate(cancel,lambda target:target['phases'][0]['result'].update(concurrency_limit=1))
        mutate(flow,lambda target:target['phases'][1]['result']['brief'].update(complete=False))
        def duplicate_terminal(target):
            events=target['phases'][1]['events'];events.append(deepcopy(events[-1]))
            target['phases'][1]['events']=self.resequenced(events)
        mutate(flow,duplicate_terminal)
        path=Path(flow['phases'][1]['trace_path'])
        for content in ['\n','{not json}\n',json.dumps(flow['phases'][1]['events'][0])+'\n\n','{"value":NaN}\n']:
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
                       lambda t,p:t['testResults'][1]['assertionResults'][0].update(status='skipped'),
                       lambda t,p:t['testResults'][1].update(name='test/unknown.test.ts'),
                       lambda t,p:p.update(tests_run=0),
                       lambda t,p:p.update(passed=p['passed'][1:]),
                       lambda t,p:p.update(discovered=['unittest.loader._FailedTest.test_executor']),
                       lambda t,p:p.update(successful=False)]:
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

    def test_stale_output_removed_before_first_gate_command(self):
        from scripts import verify_m4 as authority
        output=self.root/'m4';output.mkdir();(output/'verification-evidence.json').write_text('old')
        def stop(*args,**kwargs):
            self.assertFalse((output/'verification-evidence.json').exists())
            raise RuntimeError('lower chain failed')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='start'),patch.object(authority,'run',side_effect=stop):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse((output/'verification-evidence.json').exists())

    def test_python_suite_sets_and_restores_child_import_path(self):
        from scripts import verify_m4 as authority
        class ChildImportTest(unittest.TestCase):
            def runTest(self):
                subprocess.run([sys.executable,'-c','import boundrelay_m4'],cwd=ROOT,capture_output=True,check=True)
        import os
        with patch.dict(os.environ,{},clear=True),patch.object(unittest.TestLoader,'discover',return_value=unittest.TestSuite([ChildImportTest()])):
            report=authority.run_python_suite()
            self.assertTrue(report['successful'])
            self.assertNotIn('PYTHONPATH',os.environ)

    def test_stale_output_removed_for_dirty_preflight(self):
        from scripts import verify_m4 as authority
        output=self.root/'m4';output.mkdir()
        stale=output/'verification-evidence.json';stale.write_text('{"status":"PASSED"}')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree',side_effect=RuntimeError('dirty')):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse(stale.exists())

    def test_evidence_clear_rejects_symlink_redirect(self):
        root=self.root
        for placement in ('leaf','parent'):
            with self.subTest(placement=placement):
                external=root/placement/'outside'/'m4'
                external.mkdir(parents=True)
                marker=external/'important.txt';marker.write_text('preserve',encoding='utf-8')
                workspace=root/placement/'workspace';workspace.mkdir(parents=True)
                output=workspace/'.boundrelay'/'m4'
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
        nested=M4VerificationSafetyTests('test_stale_output_removed_before_first_gate_command')
        fake=SimpleNamespace(name=str(alias),cleanup=lambda: None)
        with patch.object(tempfile,'TemporaryDirectory',return_value=fake):nested.setUp()
        try:
            self.assertEqual(Path(nested.path).parent,resolved)
            nested.test_stale_output_removed_before_first_gate_command()
        finally:nested.doCleanups()


if __name__=='__main__':unittest.main()
