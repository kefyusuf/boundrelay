import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from boundrelay_m5.cli import parse_cli_options,run_cli
from boundrelay_m5.effect_ledger import EffectLedger
from boundrelay_m5.audit import AuditWriter
from boundrelay_m5.state_store import load_run_state
from boundrelay_m5.types import StateBinding

SRC=Path(__file__).resolve().parents[1]/'src'

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

def spawn(args):
    env={**os.environ,'PYTHONPATH':str(SRC)}
    process=subprocess.run([sys.executable,'-m','boundrelay_m5',*args],capture_output=True,text=True,timeout=120,env=env)
    return process.returncode,process.stdout,process.stderr

def trace_events(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]

class CliTests(unittest.TestCase):
    def test_strict_cli_rejects_invalid_arguments(self):
        base=['--case','approval-granted-effect-once','--trace','trace.jsonl','--state-dir','state']
        parsed=parse_cli_options(base)
        self.assertEqual(parsed['case_id'],'approval-granted-effect-once');self.assertFalse(parsed['resume'])
        self.assertTrue(parse_cli_options(base+['--resume'])['resume'])
        for args in [[],base[2:],base+['--case','other'],base+['--unknown','x'],base+['positional'],
                     ['--case','--trace']+base[2:],base+['--resume','value'],
                     ['--case','approval-granted-effect-once','--trace','trace.jsonl'],['--state-dir','state','--trace','trace.jsonl']]:
            with self.assertRaises(ValueError):parse_cli_options(args)
    def test_tooling_error_has_exit_two_and_no_result(self):
        stdout=[];stderr=[]
        code=run_cli(['--case','unknown-case','--trace','unused.jsonl','--state-dir','state'],stdout.append,stderr.append)
        self.assertEqual(code,2);self.assertEqual(stdout,[]);self.assertTrue(stderr)
class MultiPhaseTests(unittest.TestCase):
    def test_approval_granted_effect_once_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace=str(Path(tmp)/'run.jsonl')
            code,stdout,_=spawn(['--case','approval-granted-effect-once','--trace',trace,'--state-dir',state_dir])
            self.assertEqual(code,0);self.assertEqual(len(stdout.strip().splitlines()),1)
            result=json.loads(stdout)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(result['approval_decision'],'granted')
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
            order=[e['type'] for e in trace_events(trace)]
            self.assertLess(order.index('approval.granted'),order.index('tool.requested'))
            self.assertLess(order.index('tool.completed'),order.index('run.completed'))
    def test_approval_rejected_no_effect_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace=str(Path(tmp)/'run.jsonl')
            code,stdout,_=spawn(['--case','approval-rejected-no-effect','--trace',trace,'--state-dir',state_dir])
            self.assertEqual(code,0)
            result=json.loads(stdout)
            self.assertEqual(result['status'],'FAILED');self.assertEqual(result['failure_code'],'APPROVAL_REJECTED')
            self.assertEqual(EffectLedger(state_dir).records(),[])
            audit=AuditWriter(state_dir).records()
            self.assertEqual(len(audit),1);self.assertEqual(audit[0]['kind'],'approval');self.assertEqual(audit[0]['decision'],'rejected')
            self.assertFalse(any(e['type'].startswith('tool.') for e in trace_events(trace)))
    def test_retry_before_submit_two_phase_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,stdout,_=spawn(['--case','retry-before-submit','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,2);self.assertEqual(stdout,'')
            phase1=trace_events(trace1)
            self.assertEqual(phase1[0]['type'],'run.created')
            self.assertTrue(any(e['type']=='approval.granted' for e in phase1))
            self.assertFalse(any(e['type'].startswith('tool.') for e in phase1))
            self.assertFalse(any(e['type'] in ('run.completed','run.failed') for e in phase1))
            code,stdout,_=spawn(['--case','retry-before-submit','--trace',trace2,'--state-dir',state_dir,'--resume'])
            self.assertEqual(code,0);self.assertEqual(len(stdout.strip().splitlines()),1)
            result=json.loads(stdout)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertFalse(result['reconciled']);self.assertTrue(result['resumed'])
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
    def test_crash_submit_window_resolved_two_phase_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,stdout,_=spawn(['--case','crash-submit-window-resolved','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,2);self.assertEqual(stdout,'')
            self.assertTrue(any(e['type']=='tool.requested' for e in trace_events(trace1)))
            code,stdout,_=spawn(['--case','crash-submit-window-resolved','--trace',trace2,'--state-dir',state_dir,'--resume'])
            self.assertEqual(code,0)
            result=json.loads(stdout)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertTrue(result['reconciled']);self.assertTrue(result['resumed'])
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
    def test_sink_unavailable_unknown_two_phase_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,_,_=spawn(['--case','sink-unavailable-unknown','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,2)
            code,stdout,_=spawn(['--case','sink-unavailable-unknown','--trace',trace2,'--state-dir',state_dir,'--resume'])
            self.assertEqual(code,0)
            result=json.loads(stdout)
            self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(result['effect_status'],'EFFECT_UNPROVABLE')
            self.assertIsNone(result['failure_code']);self.assertFalse(result['reconciled'])
            self.assertEqual(result['run_state_status'],'UNKNOWN');self.assertEqual(result['idempotency_key'],'cancel-and-refund:ORD-1001')
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
            self.assertTrue(any(e['type'] in ('run.completed','run.failed') for e in trace_events(trace2)))
    def test_duplicate_key_suppressed_two_runs_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'run1.jsonl');trace2=str(Path(tmp)/'run2.jsonl')
            code,stdout,_=spawn(['--case','duplicate-key-suppressed','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,0)
            one=json.loads(stdout)
            self.assertEqual(one['status'],'SUCCEEDED');self.assertFalse(one['reconciled'])
            code,stdout,_=spawn(['--case','duplicate-key-suppressed','--trace',trace2,'--state-dir',state_dir])
            self.assertEqual(code,0)
            two=json.loads(stdout)
            self.assertEqual(two['status'],'SUCCEEDED');self.assertFalse(two['reconciled'])
            self.assertEqual(two['idempotency_key'],'cancel-and-refund:ORD-1001')
            self.assertEqual(len(EffectLedger(state_dir).records()),1)
            doc=json.loads((Path(state_dir)/str(two['run_id'])/'state.json').read_text(encoding='utf-8'))
            self.assertTrue(doc['effect']['duplicate'])



