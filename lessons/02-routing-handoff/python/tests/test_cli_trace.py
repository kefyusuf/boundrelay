import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from boundrelay_m2.cli import main, parse_cli_options
from boundrelay_m2.trace import MemoryEventSink


class CliTraceTests(unittest.TestCase):
    def test_cli_strict_options(self):
        args = ['--mode','code','--case','code-billing-handoff','--trace','t.jsonl']
        self.assertEqual(parse_cli_options(args), {'mode':'code','case_id':'code-billing-handoff','trace_path':'t.jsonl'})
        for bad in (args+['--mode','model'],args+['--other','x'],args+['positional'],['--mode'],['--mode','auto']+args[2:]):
            with self.assertRaises(ValueError): parse_cli_options(bad)

    def test_cli_one_result_and_tooling_error(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode, case, status in [('code','code-billing-handoff','SUCCEEDED'),('model','handoff-context-loss','FAILED')]:
                out,err=io.StringIO(),io.StringIO()
                with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                    code=main(['--mode',mode,'--case',case,'--trace',str(Path(directory)/'t.jsonl')])
                self.assertEqual(code,0)
                self.assertEqual(len(out.getvalue().splitlines()),1)
                self.assertEqual(json.loads(out.getvalue())['status'],status)
                self.assertEqual(err.getvalue(),'')
            async def broken(**kwargs): raise RuntimeError('receiver bug')
            out,err=io.StringIO(),io.StringIO()
            with patch('boundrelay_m2.cli.run_scenario_case',broken),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                self.assertEqual(main(['--mode','code','--case','code-billing-handoff','--trace','t']),2)
            self.assertEqual(out.getvalue(),'')
            self.assertIn('receiver bug',err.getvalue())

    def test_trace_snapshots_and_json_safety(self):
        sink=MemoryEventSink(run_id='run',source='python')
        data={'decision':{'route':'billing','confidence':float('inf')}}
        sink.emit('model.completed',data)
        data['decision']['route']='changed'
        copy=sink.events
        copy[0]['data']['extra']=True
        self.assertEqual(sink.events[0]['data'],{'decision':{'route':'billing','confidence':None}})
        with self.assertRaises(ValueError): MemoryEventSink(run_id='',source='python').emit('run.started',{})
