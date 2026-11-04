import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from boundrelay_m4.cli import parse_cli_options,run_cli
from boundrelay_m4.state_store import load_run_state
from boundrelay_m4.types import StateBinding

SRC=Path(__file__).resolve().parents[1]/'src'

def binding(case_id):
    return StateBinding(case_id=case_id,execution_mode='parallel',requested_order_id='ORD-1001',concurrency_limit=2)

def spawn(args):
    env={**os.environ,'PYTHONPATH':str(SRC)}
    process=subprocess.run([sys.executable,'-m','boundrelay_m4',*args],capture_output=True,text=True,timeout=120,env=env)
    return process.returncode,process.stdout,process.stderr

def trace_events(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]

class CliTests(unittest.TestCase):
    def test_strict_cli_rejects_invalid_arguments(self):
        base=['--case','parallel-crash-resume','--trace','trace.jsonl','--state-dir','state']
        parsed=parse_cli_options(base)
        self.assertEqual(parsed['case_id'],'parallel-crash-resume');self.assertFalse(parsed['resume'])
        self.assertIsNone(parsed['replay_from'])
        self.assertTrue(parse_cli_options(base+['--resume'])['resume'])
        self.assertEqual(parse_cli_options(base+['--replay-from','snap.json'])['replay_from'],'snap.json')
        for args in [[],base[2:],base+['--case','other'],base+['--unknown','x'],base+['positional'],
                     ['--case','--trace']+base[2:],base+['--resume','value'],base+['--resume','--replay-from','snap.json'],
                     ['--case','parallel-crash-resume','--trace','trace.jsonl'],['--state-dir','state','--trace','trace.jsonl']]:
            with self.assertRaises(ValueError):parse_cli_options(args)
    def test_tooling_error_has_exit_two_and_no_result(self):
        stdout=[];stderr=[]
        code=run_cli(['--case','unknown-case','--trace','unused.jsonl','--state-dir','state'],stdout.append,stderr.append)
        self.assertEqual(code,2);self.assertEqual(stdout,[]);self.assertTrue(stderr)

class MultiPhaseTests(unittest.TestCase):
    def test_crash_resume_two_phase_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,stdout,_=spawn(['--case','parallel-crash-resume','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,2);self.assertEqual(stdout,'')
            events=trace_events(trace1)
            self.assertEqual(events[0]['type'],'run.created');self.assertEqual(events[-1]['type'],'checkpoint.saved')
            self.assertFalse(any(e['type'] in ('run.completed','run.failed','run.cancelled') for e in events))
            document=load_run_state(state_dir,binding('parallel-crash-resume'))['document']
            self.assertEqual(document['status'],'RUNNING')
            self.assertEqual([step['status'] for step in document['steps']],['SUCCEEDED','SUCCEEDED','PENDING'])
            self.assertEqual(document['sequence_cursor'],2)
            code,stdout,_=spawn(['--case','parallel-crash-resume','--trace',trace2,'--state-dir',state_dir,'--resume'])
            self.assertEqual(code,0);self.assertEqual(len(stdout.strip().splitlines()),1)
            result=json.loads(stdout)
            self.assertEqual(result['status'],'SUCCEEDED');self.assertTrue(result['resumed'])
            self.assertEqual(result['restored_cursor'],2)
            self.assertEqual(result['restored_worker_ids'],['order-details','payment-status'])
            self.assertEqual(result['run_state_status'],'SUCCEEDED')
            self.assertEqual(load_run_state(state_dir,binding('parallel-crash-resume'))['document']['status'],'SUCCEEDED')
    def test_cancel_resume_two_phase_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,stdout,_=spawn(['--case','parallel-cancel-resume','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,0)
            first=json.loads(stdout)
            self.assertEqual(first['status'],'CANCELLED');self.assertIsNone(first['failure_code'])
            self.assertFalse(first['synthesis_invoked'])
            self.assertTrue(any(e['type']=='run.cancelled' for e in trace_events(trace1)))
            document=load_run_state(state_dir,binding('parallel-cancel-resume'))['document']
            self.assertEqual(document['status'],'CANCELLED')
            self.assertEqual([step['status'] for step in document['steps']],['SUCCEEDED','SUCCEEDED','CANCELLED'])
            code,stdout,_=spawn(['--case','parallel-cancel-resume','--trace',trace2,'--state-dir',state_dir,'--resume'])
            self.assertEqual(code,0)
            second=json.loads(stdout)
            self.assertEqual(second['status'],'SUCCEEDED');self.assertTrue(second['resumed'])
            self.assertEqual(second['restored_cursor'],2)
            self.assertEqual(second['restored_worker_ids'],['order-details','payment-status'])
    def test_replay_from_checkpoint_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,stdout,_=spawn(['--case','parallel-replay-from-checkpoint','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,0)
            first=json.loads(stdout);run_dir=Path(state_dir)/first['run_id'];snapshot=run_dir/'checkpoints'/'step-1.json'
            before_state=(run_dir/'state.json').read_text(encoding='utf-8');before_snapshot=snapshot.read_text(encoding='utf-8')
            code,stdout,_=spawn(['--case','parallel-replay-from-checkpoint','--trace',trace2,'--state-dir',state_dir,'--replay-from',snapshot])
            self.assertEqual(code,0)
            second=json.loads(stdout)
            self.assertNotEqual(second['run_id'],first['run_id']);self.assertEqual(second['status'],'SUCCEEDED')
            self.assertTrue(second['resumed']);self.assertEqual(second['restored_cursor'],1)
            self.assertEqual(second['restored_worker_ids'],['order-details'])
            self.assertEqual((run_dir/'state.json').read_text(encoding='utf-8'),before_state)
            self.assertEqual(snapshot.read_text(encoding='utf-8'),before_snapshot)
    def test_corrupt_state_resume_fails_closed_subprocess(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state_dir=str(Path(tmp)/'state');trace1=str(Path(tmp)/'phase1.jsonl');trace2=str(Path(tmp)/'phase2.jsonl')
            code,_,_=spawn(['--case','parallel-crash-resume','--trace',trace1,'--state-dir',state_dir])
            self.assertEqual(code,2)
            state_path=Path(load_run_state(state_dir,binding('parallel-crash-resume'))['restored_from'])
            tampered=json.loads(state_path.read_text(encoding='utf-8'))
            tampered['steps'][1]['output']['payment_status']='UNPAID'
            state_path.write_text(json.dumps(tampered),encoding='utf-8')
            tampered_bytes=state_path.read_text(encoding='utf-8')
            code,stdout,stderr=spawn(['--case','parallel-crash-resume','--trace',trace2,'--state-dir',state_dir,'--resume'])
            self.assertEqual(code,2);self.assertEqual(stdout,'');self.assertTrue(stderr)
            self.assertEqual(state_path.read_text(encoding='utf-8'),tampered_bytes)


