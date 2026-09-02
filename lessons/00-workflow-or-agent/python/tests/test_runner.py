from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from boundrelay_m0.runner import run_scenario_case


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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class RunnerTests(unittest.TestCase):
    def test_runs_a_valid_model_route_with_one_terminal_event_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            socket, "create_connection", side_effect=AssertionError("network access is forbidden")
        ):
            trace_path = Path(directory) / "trace.jsonl"
            result = run_scenario_case(
                mode="model",
                case_id="billing-duplicate-charge",
                trace_path=str(trace_path),
                clock=fixed_clock,
                id_factory=fixed_ids("valid"),
            )
            events = read_events(trace_path)

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(result.selected_route, "billing")
        self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(sum(event["type"] in {"run.completed", "run.failed"} for event in events), 1)
        self.assertEqual(events[-1]["type"], "run.completed")

    def test_fails_closed_for_an_invalid_model_route_without_a_specialist_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            socket, "create_connection", side_effect=AssertionError("network access is forbidden")
        ):
            trace_path = Path(directory) / "trace.jsonl"
            result = run_scenario_case(
                mode="model",
                case_id="invalid-model-route",
                trace_path=str(trace_path),
                clock=fixed_clock,
                id_factory=fixed_ids("invalid"),
            )
            events = read_events(trace_path)

        self.assertEqual(result.status, "FAILED")
        self.assertIsNone(result.selected_route)
        self.assertFalse(result.specialist_invoked)
        self.assertEqual(result.failure_code, "INVALID_ROUTE_DECISION")
        self.assertTrue(any(event["type"] == "route.rejected" for event in events))
        self.assertEqual(sum(event["type"] in {"run.completed", "run.failed"} for event in events), 1)
        self.assertEqual(events[-1]["type"], "run.failed")
        self.assertFalse(any(str(event["data"].get("step", "")).startswith("specialist.") for event in events))


if __name__ == "__main__":
    unittest.main()
