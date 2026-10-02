from dataclasses import asdict
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from boundrelay_m2.runner import run_scenario_case
from boundrelay_m2.scenario import load_scenario
from boundrelay_m2.types import ReceiverDefinition


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_canonical_lifecycles_and_actual_invocations(self):
        with tempfile.TemporaryDirectory() as directory:
            for c in load_scenario().cases:
                with self.subTest(case=c.id):
                    calls, resolutions = [], []
                    async def handle(input): calls.append(asdict(input))
                    class Directory:
                        def resolve(self, name):
                            resolutions.append(name)
                            return None if c.id == 'handoff-receiver-unavailable' else ReceiverDefinition(name, handle)
                    trace = str(Path(directory)/'trace.jsonl')
                    result = await run_scenario_case(mode=c.router_mode, case_id=c.id, trace_path=trace, receiver_directory=Directory())
                    for key in ('status','proposed_route','selected_route','receiver','fallback_applied','specialist_invoked','failure_code'):
                        self.assertEqual(getattr(result,key), getattr(c,'expected_'+key))
                    self.assertEqual(calls, [{'ticket_id': c.ticket_id, 'request_text': c.request}] if c.expected_specialist_invoked else [])
                    self.assertEqual(resolutions, [] if c.id == 'handoff-context-loss' else [c.expected_receiver])
                    events = [json.loads(line) for line in Path(trace).read_text(encoding='utf-8').splitlines()]
                    expected = ['run.created','run.started'] + (['model.requested','model.completed'] if c.router_mode == 'model' else []) + ['route.selected','handoff.requested','handoff.accepted' if c.expected_specialist_invoked else 'handoff.rejected','run.completed' if c.expected_specialist_invoked else 'run.failed']
                    self.assertEqual([e['type'] for e in events], expected)
                    self.assertEqual([e['sequence'] for e in events], list(range(1,len(events)+1)))
                    self.assertTrue(all(e['run_id'] == result.run_id for e in events))
                    request = next(e['data'] for e in events if e['type'] == 'handoff.requested')
                    self.assertEqual(request['sender_intent'], {'route': c.expected_proposed_route,'confidence': c.expected_confidence,'policy_outcome': c.expected_policy_outcome})
                    self.assertEqual(request['receiver_input'], {'ticket_id': c.ticket_id} if c.id == 'handoff-context-loss' else {'ticket_id': c.ticket_id,'request_text': c.request})
                    self.assertEqual(events[-2]['data']['handoff_id'], request['handoff_id'])

    async def test_invalid_route_never_resolves_receiver(self):
        with tempfile.TemporaryDirectory() as directory:
            for raw in ({'route':'unknown','confidence':1}, {'route':'billing','confidence':float('nan')}, {'route':'billing','confidence':.9,'receiver':'general-specialist'}):
                class Provider:
                    async def next_decision(self, **kwargs): return raw
                class Directory:
                    def resolve(self, name): raise AssertionError('must not resolve')
                trace = str(Path(directory)/'trace.jsonl')
                result = await run_scenario_case(mode='model',case_id='model-technical-handoff',trace_path=trace,route_provider=Provider(),receiver_directory=Directory())
                self.assertEqual(result.failure_code,'INVALID_ROUTE_DECISION')
                self.assertIsNone(result.proposed_route)
                events = [json.loads(line) for line in Path(trace).read_text().splitlines()]
                self.assertEqual([e['type'] for e in events], ['run.created','run.started','model.requested','model.completed','route.rejected','run.failed'])

    async def test_receiver_exception_propagates_without_retry(self):
        calls = []
        async def broken(input): calls.append(input); raise RuntimeError('receiver bug')
        class Directory:
            def resolve(self, name): return ReceiverDefinition(name,broken)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,'receiver bug'):
                await run_scenario_case(mode='code',case_id='code-billing-handoff',trace_path=str(Path(directory)/'trace.jsonl'),receiver_directory=Directory())
        self.assertEqual(len(calls),1)

    async def test_all_canonical_runs_under_network_guard(self):
        original = socket.socket.connect
        def connect(sock,address):
            if sock.family in (socket.AF_INET,socket.AF_INET6): raise RuntimeError('network denied')
            return original(sock,address)
        with patch('socket.create_connection',side_effect=RuntimeError('network denied')), patch.object(socket.socket,'connect',connect):
            await self.test_all_canonical_lifecycles_and_actual_invocations()

    def test_fresh_import_with_network_denied(self):
        code = '''
import socket
original = socket.socket.connect
def blocked(*a, **k): raise RuntimeError('network denied')
def connect(sock,address):
    if sock.family in (socket.AF_INET,socket.AF_INET6): return blocked()
    return original(sock,address)
socket.create_connection=blocked
socket.socket.connect=connect
try: socket.create_connection(('127.0.0.1',9))
except RuntimeError: pass
else: raise AssertionError('guard missing')
import boundrelay_m2.runner
print('offline-imported')
'''
        process = subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(process.stdout.strip(),'offline-imported')
