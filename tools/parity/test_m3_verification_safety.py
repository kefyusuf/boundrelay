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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'lessons/03-parallel-fanout-fanin/python/src'))
from boundrelay_m3.runner import run_case
from boundrelay_m3.scenario import load_scenario
from tools.parity import verify_m3 as gate
from tools.parity.normalize import read_jsonl


class M3VerificationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'trace.jsonl')
        self.case = asdict(load_scenario().cases[1])
        self.result = asyncio.run(run_case(case_id=self.case['case_id'],trace_path=self.path))
        self.events = read_jsonl(self.path)

    def test_raw_mutations_fail_before_projection(self):
        gate.assert_case_behavior(self.result,self.events,self.case,self.path,'python')
        for mutate in [
            lambda r,e: e.insert(3,deepcopy(e[2])),
            lambda r,e: e.pop(2),
            lambda r,e: e[2]['data'].update(worker_id='payment-status'),
            lambda r,e: e[2]['data'].update(order_id='ORD-9999'),
            lambda r,e: e[0]['data'].update(execution_mode='sequential'),
            lambda r,e: e[1].update(source='typescript'),
            lambda r,e: e[1].update(run_id='other'),
            lambda r,e: e[3].update(sequence=99),
            lambda r,e: e[3].update(event_id=e[2]['event_id']),
            lambda r,e: r.update(trace_path='other'),
            lambda r,e: r.update(concurrency_limit=1),
            lambda r,e: r.update(peak_concurrency=1),
            lambda r,e: r['brief'].update(complete=False),
            lambda r,e: r['brief']['sections'][1]['output'].update(payment_status='UNPAID'),
            lambda r,e: e.insert(4,e.pop(-3)),
            lambda r,e: e.insert(len(e)-1,deepcopy(e[-1])),
            lambda r,e: e[-1]['data'].update(status='PARTIAL'),
            lambda r,e: e[4]['data'].update(private_note='secret'),
        ]:
            r,e=deepcopy(self.result),deepcopy(self.events)
            mutate(r,e)
            with self.subTest(mutation=mutate):
                with self.assertRaises((AssertionError,ValueError)):
                    gate.semantic_trace(r,e,self.case,self.path,'python')
        # Keep envelope IDs/sequences valid so lifecycle checks, not just envelope checks, reject duplicates.
        duplicate=deepcopy(self.events);duplicate.insert(3,deepcopy(duplicate[2]))
        for i,event in enumerate(duplicate,1):event['sequence']=i;event['event_id']=f'event-{i}'
        with self.assertRaises(AssertionError):gate.semantic_trace(self.result,duplicate,self.case,self.path,'python')
        for content in ['\n','{not json}\n',json.dumps(self.events[0])+'\n\n','{"value":NaN}\n']:
            Path(self.path).write_text(content,encoding='utf-8')
            with self.assertRaises(ValueError):read_jsonl(self.path)

    def test_case_expected_failures_cannot_be_lost(self):
        case=asdict(load_scenario().cases[3])
        result=asyncio.run(run_case(case_id=case['case_id'],trace_path=self.path))
        events=read_jsonl(self.path)
        gate.assert_case_behavior(result,events,case,self.path,'python')
        result['worker_outcomes'][2]['failure_code']='INVALID_WORKER_OUTPUT'
        events[-1]['data']['worker_outcomes']=deepcopy(result['worker_outcomes'])
        with self.assertRaises(AssertionError):gate.assert_case_behavior(result,events,case,self.path,'python')

    def reports(self):
        names=gate.REQUIRED_PROBES
        ts={'success':True,'numTotalTests':4,'numPassedTests':4,'numFailedTests':0,'numFailedTestSuites':0,
            'testResults':[{'name':'test/executor.test.ts','status':'passed','assertionResults':[
                {'title':n,'fullName':n,'status':'passed'} for n in names]}]}
        ids=[f'test_executor.ExecutorTests.test_{n}' for n in names]
        py={'successful':True,'tests_run':4,'discovered':ids,'passed':ids,'failed':[],'skipped':[]}
        return ts,py

    def test_missing_probe_or_zero_suite_cannot_certify(self):
        ts,py=self.reports();gate.validate_probe_reports(ts,py)
        for mutate in [lambda t,p:t.update(numPassedTests=0),
                       lambda t,p:t['testResults'][0]['assertionResults'].pop(),
                       lambda t,p:t['testResults'][0]['assertionResults'][0].update(status='skipped'),
                       lambda t,p:p.update(tests_run=0),
                       lambda t,p:p.update(passed=p['passed'][1:]),
                       lambda t,p:p.update(discovered=['unittest.loader._FailedTest.test_executor']),
                       lambda t,p:p.update(successful=False)]:
            t,p=deepcopy(ts),deepcopy(py);mutate(t,p)
            with self.assertRaises((RuntimeError,ValueError)):gate.validate_probe_reports(t,p)

    def test_publication_checks_survive_optimization(self):
        path=Path(self.tmp.name)/'evidence.json'
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
        from scripts import verify_m3 as authority
        output=Path(self.tmp.name)/'m3';output.mkdir();(output/'verification-evidence.json').write_text('old')
        def stop(*args,**kwargs):
            self.assertFalse((output/'verification-evidence.json').exists())
            raise RuntimeError('lower chain failed')
        with patch.object(gate,'OUTPUT_ROOT',output),patch.object(gate,'assert_clean_worktree'),patch.object(gate,'_revision',return_value='start'),patch.object(authority,'run',side_effect=stop):
            with self.assertRaises(RuntimeError):authority.main()
        self.assertFalse((output/'verification-evidence.json').exists())


if __name__=='__main__':unittest.main()
