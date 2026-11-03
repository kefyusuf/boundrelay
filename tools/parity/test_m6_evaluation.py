"""Fail-closed probes for the M6 evaluator (tools/evaluate.py).

The probes patch the evaluator's subprocess and git boundaries so the
fail-closed paths are exercised without depending on the host worktree.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import evaluate as ev

ROOT = Path(__file__).resolve().parents[2]

M0_RESULT = {
    "schema_version": "1.0", "run_id": "run-1", "scenario_id": "support-triage",
    "case_id": "billing-duplicate-charge", "mode": "model", "status": "SUCCEEDED",
    "selected_route": "billing", "specialist_invoked": True, "failure_code": None,
    "trace_path": "trace.jsonl",
    "attribution": {
        "steps": [
            {"step_name": "classify", "latency_ms": 30, "cost_cents": 2, "attempts": 1},
            {"step_name": "specialist.billing", "latency_ms": 10, "cost_cents": 0, "attempts": 1}],
        "totals": {"latency_ms": 40, "cost_cents": 2, "attempts": 2}}}

M0_EVENTS = [
    {"type": "run.created", "data": {}},
    {"type": "run.started", "data": {}},
    {"type": "step.started", "data": {"step": "classify"}},
    {"type": "model.requested", "data": {}},
    {"type": "model.completed", "data": {}},
    {"type": "route.selected", "data": {}},
    {"type": "step.completed", "data": {"step": "classify"}},
    {"type": "step.started", "data": {"step": "specialist.billing"}},
    {"type": "step.completed", "data": {"step": "specialist.billing"}},
    {"type": "run.completed", "data": {}}]


def canned_flow(**overrides):
    flow = {"result": deepcopy(M0_RESULT), "ts_result": deepcopy(M0_RESULT),
            "events": deepcopy(M0_EVENTS), "ts_events": deepcopy(M0_EVENTS)}
    flow.update(overrides)
    return flow


class M6EvaluationSafetyTests(unittest.TestCase):
    def test_missing_golden_is_a_tooling_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ev, "GOLDEN_ROOT", Path(directory)):
                actual = ev.flow_evidence(canned_flow())
                with self.assertRaises(ev.ToolingError) as caught:
                    ev.compare_with_golden("support-triage", "billing-duplicate-charge@model", actual)
        self.assertIn("Missing golden", str(caught.exception))

    def test_language_run_failure_is_a_tooling_error(self):
        def failing_spawn(command):
            if "npm" in command[0]:
                return 2, "", "boom"
            trace = command[command.index("--trace") + 1]
            Path(trace).write_text(json.dumps(M0_EVENTS[0]) + "\n", encoding="utf-8")
            return 0, json.dumps(deepcopy(M0_RESULT)), ""
        with patch.object(ev, "_spawn", side_effect=failing_spawn):
            with self.assertRaises(ev.ToolingError) as caught:
                ev.run_flow("support-triage", {"key": "billing-duplicate-charge@model",
                                               "case_id": "billing-duplicate-charge",
                                               "mode": "model"}, Path(tempfile.mkdtemp()))
        self.assertIn("typescript", str(caught.exception))

    def test_language_divergence_is_a_tooling_error(self):
        diverged = deepcopy(M0_RESULT)
        diverged["selected_route"] = "technical"
        with self.assertRaises(ev.ToolingError) as caught:
            ev.flow_evidence(canned_flow(ts_result=diverged))
        self.assertIn("typescript and python", str(caught.exception))

    def test_regenerate_requires_clean_worktree(self):
        with patch.object(ev, "_git_status", return_value=" M some/file.py"):
            with self.assertRaises(ev.ToolingError) as caught:
                ev.regenerate("support-triage", "billing-duplicate-charge@model")
        self.assertIn("clean worktree", str(caught.exception))

    def test_report_shape_on_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            golden_root = root / "goldens"
            with patch.object(ev, "GOLDEN_ROOT", golden_root), \
                 patch.object(ev, "_git_status", return_value=""), \
                 patch.object(ev, "run_flow", return_value=canned_flow()):
                ev.regenerate("support-triage", "billing-duplicate-charge@model")
                report_path = root / "report.json"
                report = ev.evaluate(["support-triage"], report_path=report_path,
                                     only_case="billing-duplicate-charge@model")
            self.assertEqual(report["cases"][0]["status"], "PASS")
            self.assertEqual(report["totals"], {"passed": 1, "failed": 0})
            written = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(written["schema_version"], "1.0")
            self.assertEqual(written["cases"][0]["case_key"], "billing-duplicate-charge@model")
            golden = json.loads((golden_root / "support-triage" /
                                 "billing-duplicate-charge@model.json").read_text(encoding="utf-8"))
            self.assertEqual(golden["languages"], ["typescript", "python"])
            self.assertIn("event_sequence", golden)
            self.assertIn("attribution", golden)
