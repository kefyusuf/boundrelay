from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from boundrelay_m1.types import ToolDefinition, ToolObservation, ValidationSuccess

run_scenario_case = None


def fixed_ids(prefix: str):
    sequence = 0
    def next_id() -> str:
        nonlocal sequence
        sequence += 1
        return f"{prefix}-{sequence}"
    return next_id


def fixed_clock() -> datetime:
    return datetime(2026, 9, 29, tzinfo=timezone.utc)


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class RecordingProvider:
    def __init__(self) -> None:
        self.inputs: list[tuple] = []
        self.turns = (
            {"schema_version":"1.0","decision":{"kind":"tool_call","call_id":"call-1","tool":"lookup_order","arguments":{"order_id":"ORD-1001"}},"usage":{"input_tokens":50,"output_tokens":10}},
            {"schema_version":"1.0","decision":{"kind":"tool_call","call_id":"call-2","tool":"lookup_shipment","arguments":{"shipment_id":"SHP-1001"}},"usage":{"input_tokens":30,"output_tokens":10}},
            {"schema_version":"1.0","decision":{"kind":"final","answer":"Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather."},"usage":{"input_tokens":20,"output_tokens":9}},
        )

    async def next_turn(self, *, case_id, request, model_step, observations):
        self.inputs.append((case_id, request, model_step, deepcopy(observations)))
        return deepcopy(self.turns[model_step - 1])


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        global run_scenario_case
        original_connect = socket.socket.connect
        def guarded_connect(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("network access is forbidden")
            return original_connect(sock, address)
        cls._create_connection = patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network access is forbidden"),
        )
        cls._socket_connect = patch.object(socket.socket, "connect", new=guarded_connect)
        cls._create_connection.start()
        cls._socket_connect.start()
        try:
            with cls.assertRaises(cls, AssertionError):
                socket.create_connection(("127.0.0.1", 9), timeout=0.01)
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with cls.assertRaises(cls, AssertionError):
                    probe.connect(("127.0.0.1", 9))
            finally:
                probe.close()
            from boundrelay_m1.runner import run_scenario_case as runner
            run_scenario_case = runner
        except Exception:
            cls._socket_connect.stop()
            cls._create_connection.stop()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls._socket_connect.stop()
        cls._create_connection.stop()

    async def run_case(self, case_id: str, mode: str, **overrides):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "trace.jsonl"
        result = await run_scenario_case(
            mode=mode, case_id=case_id, trace_path=str(path),
            clock=fixed_clock, id_factory=fixed_ids(case_id), **overrides,
        )
        return result, read_events(path)

    async def test_direct_success_has_zero_model_events(self) -> None:
        result, events = await self.run_case("direct-order-status", "direct")
        self.assertEqual((result.status, result.answer, result.model_steps, result.tokens_used, result.tool_invocations),
                         ("SUCCEEDED", "Order ORD-1001 status is SHIPPED.", 0, 0, 1))
        self.assertFalse(any(event["type"].startswith("model.") for event in events))
        self.assertEqual(events[-1]["type"], "run.completed")

    async def test_agent_success_passes_observations_and_hits_exact_budgets(self) -> None:
        provider = RecordingProvider()
        result, events = await self.run_case("agent-delayed-shipment", "agent", model_provider=provider)
        self.assertEqual((result.status, result.model_steps, result.tokens_used, result.tool_invocations), ("SUCCEEDED", 3, 129, 2))
        self.assertEqual([e["data"]["tool"] for e in events if e["type"] == "tool.requested"], ["lookup_order", "lookup_shipment"])
        self.assertEqual(provider.inputs[1][3][0], ToolObservation("call-1", "lookup_order", {"order_id":"ORD-1001","status":"SHIPPED","shipment_id":"SHP-1001"}))
        self.assertEqual(provider.inputs[2][3][1], ToolObservation("call-2", "lookup_shipment", {"shipment_id":"SHP-1001","status":"DELAYED","reason":"WEATHER"}))
        self.assertFalse(any(e["type"].startswith("step.") for e in events))

    async def test_canonical_failures_have_exact_counters(self) -> None:
        cases = (
            ("agent-unknown-tool", "UNKNOWN_TOOL", 0, 1, 25),
            ("agent-invalid-arguments", "INVALID_TOOL_ARGUMENTS", 0, 1, 25),
            ("agent-tool-timeout", "TOOL_TIMEOUT", 1, 1, 25),
            ("agent-tool-failure", "TOOL_EXECUTION_FAILED", 1, 1, 25),
            ("agent-step-budget", "STEP_BUDGET_EXCEEDED", 1, 2, 50),
            ("agent-token-budget", "TOKEN_BUDGET_EXCEEDED", 1, 2, 75),
        )
        for case_id, code, invocations, steps, tokens in cases:
            with self.subTest(case_id=case_id):
                result, events = await self.run_case(case_id, "agent")
                self.assertEqual((result.status, result.failure_code, result.tool_invocations, result.model_steps, result.tokens_used),
                                 ("FAILED", code, invocations, steps, tokens))
                self.assertEqual(sum(e["type"] == "tool.requested" for e in events), invocations)
                if code in ("TOOL_TIMEOUT", "TOOL_EXECUTION_FAILED"):
                    self.assertEqual(sum(e["type"] == "tool.failed" for e in events), 1)

    async def test_invalid_model_and_provider_error_fail_closed(self) -> None:
        class Invalid:
            async def next_turn(self, **kwargs):
                return {"schema_version":"1.0","decision":{"kind":"final","answer":"x"},"usage":{"input_tokens":"bad","output_tokens":999}}
        result, events = await self.run_case("agent-delayed-shipment", "agent", model_provider=Invalid())
        self.assertEqual((result.failure_code, result.model_steps, result.tokens_used, result.tool_invocations), ("INVALID_MODEL_DECISION", 1, 0, 0))
        self.assertFalse(any(e["type"] in ("budget.consumed", "tool.requested") for e in events))

        class Explodes:
            async def next_turn(self, **kwargs):
                raise RuntimeError("exhausted")
        result, events = await self.run_case("agent-delayed-shipment", "agent", model_provider=Explodes())
        self.assertEqual((result.failure_code, result.model_steps, result.tokens_used), ("INVALID_MODEL_DECISION", 1, 0))
        self.assertEqual(sum(e["type"] == "model.failed" for e in events), 1)

    async def test_direct_mode_uses_same_timeout_executor(self) -> None:
        import asyncio
        async def never(arguments):
            await asyncio.Future()
            return {}
        definition = ToolDefinition("lookup_order", "READ_ONLY", 5, lambda value: ValidationSuccess(value), never)
        class Registry:
            def resolve(self, name):
                return definition if name == "lookup_order" else None
        result, events = await self.run_case("direct-order-status", "direct", tool_registry=Registry())
        self.assertEqual((result.failure_code, result.tool_invocations, result.model_steps, result.tokens_used), ("TOOL_TIMEOUT", 1, 0, 0))
        self.assertFalse(any(e["type"].startswith("model.") for e in events))

    async def test_all_eight_canonical_runs_stay_offline(self) -> None:
        cases = (
            ("direct-order-status", "direct"), ("agent-delayed-shipment", "agent"),
            ("agent-unknown-tool", "agent"), ("agent-invalid-arguments", "agent"),
            ("agent-tool-timeout", "agent"), ("agent-tool-failure", "agent"),
            ("agent-step-budget", "agent"), ("agent-token-budget", "agent"),
        )
        for case_id, mode in cases:
            with self.subTest(case_id=case_id):
                await self.run_case(case_id, mode)

    def test_runner_import_is_network_denied_in_fresh_interpreter(self) -> None:
        code = textwrap.dedent('''
        import socket
        class Block(RuntimeError): pass
        original_connect=socket.socket.connect
        def blocked_create_connection(*args,**kwargs):
            raise Block("network access is forbidden")
        def blocked_connect(sock,address):
            if sock.family in (socket.AF_INET,socket.AF_INET6):
                raise Block("network access is forbidden")
            return original_connect(sock,address)
        socket.create_connection=blocked_create_connection
        socket.socket.connect=blocked_connect
        try: socket.create_connection(("127.0.0.1",9),timeout=.01)
        except Block: pass
        else: raise SystemExit("create_connection guard did not fire")
        probe=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            try: probe.connect(("127.0.0.1",9))
            except Block: pass
            else: raise SystemExit("socket.connect guard did not fire")
        finally:
            probe.close()
        import boundrelay_m1.runner
        print("runner-imported-under-network-guard")
        ''')
        process = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "runner-imported-under-network-guard")
