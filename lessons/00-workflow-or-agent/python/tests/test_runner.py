from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

run_scenario_case = None
RecordingSpecialistDispatcher = None


def fixed_ids(prefix: str):
    sequence = 0

    def next_id() -> str:
        nonlocal sequence
        sequence += 1
        return f"{prefix}-{sequence}"

    return next_id


def fixed_clock() -> datetime:
    return datetime(2026, 9, 2, tzinfo=timezone.utc)


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def read_events_strict(path: Path) -> list[dict[str, object]]:
    def reject_constant(value: str) -> object:
        raise ValueError(f"Non-standard JSON constant: {value}")

    return [
        json.loads(line, parse_constant=reject_constant)
        for line in path.read_text(encoding="utf-8").split("\n")
        if line
    ]


class NonFiniteDecisionProvider:
    def classify(self, *, case_id: str, request: str) -> object:
        return {"route": "billing", "confidence": float("nan")}


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        global run_scenario_case, RecordingSpecialistDispatcher
        cls._create_connection_patch = patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network access is forbidden"),
        )
        cls._socket_patch = patch.object(
            socket,
            "socket",
            side_effect=AssertionError("network access is forbidden"),
        )
        cls._create_connection_patch.start()
        cls._socket_patch.start()
        try:
            try:
                socket.create_connection(("127.0.0.1", 9), timeout=0.01)
            except AssertionError as error:
                if str(error) != "network access is forbidden":
                    raise
            else:
                raise AssertionError("network guard probe did not block socket access")

            runner_module = importlib.import_module("boundrelay_m0.runner")
            specialists_module = importlib.import_module("boundrelay_m0.specialists")
            run_scenario_case = runner_module.run_scenario_case
            RecordingSpecialistDispatcher = specialists_module.RecordingSpecialistDispatcher
        except Exception:
            cls._socket_patch.stop()
            cls._create_connection_patch.stop()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls._socket_patch.stop()
        cls._create_connection_patch.stop()

    def test_runner_import_is_network_denied_in_a_fresh_interpreter(self) -> None:
        code = textwrap.dedent(
            """
            import socket

            class NetworkAccessForbidden(RuntimeError):
                pass

            def blocked(*args, **kwargs):
                raise NetworkAccessForbidden("network access is forbidden")

            socket.create_connection = blocked
            socket.socket = blocked

            try:
                socket.create_connection(("127.0.0.1", 9), timeout=0.01)
            except NetworkAccessForbidden:
                pass
            else:
                raise SystemExit("network guard probe did not fire")

            import boundrelay_m0.runner
            print("runner-imported-under-network-guard")
            """
        )
        process = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "runner-imported-under-network-guard")

    def test_runs_a_valid_model_route_with_one_terminal_event_offline_and_one_dispatch(self) -> None:
        dispatcher = RecordingSpecialistDispatcher()
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace.jsonl"
            result = run_scenario_case(
                mode="model",
                case_id="billing-duplicate-charge",
                trace_path=str(trace_path),
                specialist_dispatcher=dispatcher,
                clock=fixed_clock,
                id_factory=fixed_ids("valid"),
            )
            events = read_events(trace_path)

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(result.selected_route, "billing")
        self.assertEqual(len(dispatcher.invocations), 1)
        self.assertEqual(dispatcher.invocations[0].route, "billing")
        self.assertEqual(dispatcher.invocations[0].request, "I was charged twice for the same invoice.")
        self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(sum(event["type"] in {"run.completed", "run.failed"} for event in events), 1)
        self.assertEqual(events[-1]["type"], "run.completed")

    def test_fails_closed_for_an_invalid_model_route_without_a_specialist_step_or_dispatch(self) -> None:
        dispatcher = RecordingSpecialistDispatcher()
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace.jsonl"
            result = run_scenario_case(
                mode="model",
                case_id="invalid-model-route",
                trace_path=str(trace_path),
                specialist_dispatcher=dispatcher,
                clock=fixed_clock,
                id_factory=fixed_ids("invalid"),
            )
            events = read_events(trace_path)

        self.assertEqual(result.status, "FAILED")
        self.assertIsNone(result.selected_route)
        self.assertFalse(result.specialist_invoked)
        self.assertEqual(result.failure_code, "INVALID_ROUTE_DECISION")
        self.assertEqual(dispatcher.invocations, ())
        self.assertTrue(any(event["type"] == "route.rejected" for event in events))
        self.assertEqual(sum(event["type"] in {"run.completed", "run.failed"} for event in events), 1)
        self.assertEqual(events[-1]["type"], "run.failed")
        self.assertFalse(any(str(event["data"].get("step", "")).startswith("specialist.") for event in events))

    def test_non_finite_model_output_is_recorded_as_strict_json_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace.jsonl"
            result = run_scenario_case(
                mode="model",
                case_id="billing-duplicate-charge",
                trace_path=str(trace_path),
                decision_provider=NonFiniteDecisionProvider(),
                clock=fixed_clock,
                id_factory=fixed_ids("non-finite"),
            )
            events = read_events_strict(trace_path)

        self.assertEqual(result.status, "FAILED")
        self.assertFalse(result.specialist_invoked)
        model_completed = next(event for event in events if event["type"] == "model.completed")
        decision = model_completed["data"]["decision"]
        self.assertIsNone(decision["confidence"])
        self.assertEqual(events[-1]["type"], "run.failed")
        self.assertFalse(any(str(event["data"].get("step", "")).startswith("specialist.") for event in events))

    def test_all_canonical_modes_are_network_denied(self) -> None:
        canonical_runs = (
            ("billing-duplicate-charge", "deterministic"),
            ("billing-duplicate-charge", "model"),
            ("technical-login-error", "deterministic"),
            ("technical-login-error", "model"),
            ("general-opening-hours", "deterministic"),
            ("general-opening-hours", "model"),
            ("invalid-model-route", "model"),
        )

        for case_id, mode in canonical_runs:
            with self.subTest(case_id=case_id, mode=mode), tempfile.TemporaryDirectory() as directory:
                run_scenario_case(
                    mode=mode,
                    case_id=case_id,
                    trace_path=str(Path(directory) / "trace.jsonl"),
                    clock=fixed_clock,
                    id_factory=fixed_ids(f"offline-{case_id}-{mode}"),
                )


if __name__ == "__main__":
    unittest.main()
