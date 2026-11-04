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
            "go_result": deepcopy(M0_RESULT),
            "events": deepcopy(M0_EVENTS), "ts_events": deepcopy(M0_EVENTS),
            "go_events": deepcopy(M0_EVENTS)}
    flow.update(overrides)
    return flow


class M6EvaluationSafetyTests(unittest.TestCase):
    def test_missing_golden_is_a_tooling_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
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

    def test_regenerate_refuses_behavior_bearing_changes(self):
        dirty = " M lessons/00-workflow-or-agent/python/src/boundrelay_m0/runner.py"
        with patch.object(ev, "_git_status", return_value=dirty):
            with self.assertRaises(ev.ToolingError) as caught:
                ev.regenerate("support-triage", "billing-duplicate-charge@model")
        self.assertIn("behavior-bearing paths", str(caught.exception))

    def test_regenerate_tolerates_harness_only_changes(self):
        with patch.object(ev, "_git_status",
                          return_value=" M tools/evaluate.py"), \
             patch.object(ev, "run_flow", return_value=canned_flow()), \
             patch.object(ev, "GOLDEN_ROOT", Path(tempfile.mkdtemp())):
            message = ev.regenerate("support-triage", "billing-duplicate-charge@model")
        self.assertIn("Golden", message)

    def test_report_shape_on_success(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
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

    def test_attribution_totals_drift_is_a_tooling_error(self):
        drifted = deepcopy(M0_RESULT["attribution"])
        drifted["totals"]["latency_ms"] += 1
        sequence = ev.event_sequence(M0_EVENTS)
        with self.assertRaises(ev.ToolingError) as caught:
            ev.validate_attribution("support-triage", drifted, sequence)
        self.assertIn("do not equal the per-step sum", str(caught.exception))

    def test_missing_step_attribution_is_a_tooling_error(self):
        incomplete = {"steps": [M0_RESULT["attribution"]["steps"][0]],
                      "totals": {"latency_ms": 30, "cost_cents": 2, "attempts": 1}}
        sequence = ev.event_sequence(M0_EVENTS)
        with self.assertRaises(ev.ToolingError) as caught:
            ev.validate_attribution("support-triage", incomplete, sequence)
        self.assertIn("missing from attribution", str(caught.exception))
        self.assertIn("specialist.billing", str(caught.exception))

    def test_main_exit_semantics(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            with patch.object(ev, "GOLDEN_ROOT", root / "goldens"), \
                 patch.object(ev, "_git_status", return_value=""), \
                 patch.object(ev, "run_flow", return_value=canned_flow()):
                ev.regenerate("support-triage", "billing-duplicate-charge@model")
                self.assertEqual(ev.main(["--scenario", "support-triage",
                                          "--case", "billing-duplicate-charge@model"]), 0)
                self.assertEqual(ev.main(["--scenario", "order-investigation",
                                          "--case", "direct-order-status"]), 2)
                self.assertEqual(ev.main(["--regenerate", "support-triage",
                                          "billing-duplicate-charge@model"]), 0)

    def test_matrix_covers_every_declared_failure_class(self):
        from tools import chaos
        matrix = chaos.load_matrix()
        rows = matrix["rows"]
        self.assertEqual(matrix["schema_version"], "1.0")
        per_lesson = {}
        for row in rows:
            per_lesson.setdefault(row["lesson"], []).append(row)
        self.assertEqual({k: len(v) for k, v in sorted(per_lesson.items())},
                         {0: 1, 1: 4, 2: 3, 3: 4, 4: 5, 5: 4})
        discovered = {scenario: {spec["key"] for spec in ev.scenario_cases(scenario)}
                      for scenario in ev.SCENARIOS}
        for row in rows:
            if row.get("case_key") is not None:
                self.assertIn(row["case_key"], discovered[row["scenario"]],
                              f"{row['failure_id']} case key must be canonical")
        for row in rows:
            for language in ("python", "typescript"):
                self.assertTrue(
                    chaos.proof_identity_exists(row["lesson"], language,
                                                row["proof"][language]),
                    f"{row['failure_id']} proof missing in {language} suite: "
                    f"{row['proof'][language]}")

    def test_matrix_rows_have_stable_ids(self):
        from tools import chaos
        rows = chaos.load_matrix()["rows"]
        seen: dict[int, int] = {}
        for row in rows:
            lesson = row["lesson"]
            seen[lesson] = seen.get(lesson, 0) + 1
            self.assertEqual(row["failure_id"], f"M{lesson}-F{seen[lesson]}",
                             "failure ids must be sequential per lesson")

    def test_chaos_replay_matches_matrix(self):
        from tools import chaos
        case_rows = [row for row in chaos.load_matrix()["rows"]
                     if row.get("case_key") is not None]
        report = chaos.replay_matrix(rows=case_rows)
        self.assertEqual({record["status"] for record in report["rows"]}, {"PASS"})
        by_id = {record["failure_id"]: record for record in report["rows"]}
        self.assertEqual(by_id["M0-F1"]["invocations"]["specialist_invoked"], False)
        self.assertEqual(by_id["M5-F4"]["invocations"]["ledger_records"], 1)
        self.assertEqual(by_id["M5-F1"]["invocations"]["ledger_empty"], True)
        self.assertEqual(by_id["M4-F3"]["exit_code"], 2)
        self.assertEqual(by_id["M1-F3"]["result"]["failure_code"], "TOOL_TIMEOUT")

    def test_chaos_exercises_all_rows(self):
        from tools import chaos
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            report_path = Path(directory) / "chaos-report.json"
            exit_code = chaos.main(["--all", "--report", str(report_path)])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["totals"], {"passed": 21, "failed": 0})
        self.assertEqual({r["status"] for r in report["rows"]}, {"PASS"})


class M7LanguageExtensionTests(unittest.TestCase):
    """M7 probes: the Go language dispatch, the --languages flag semantics,
    and the matrix's Go proof identities."""

    def setUp(self):
        ev._go_cli_cache.clear()
        self.addCleanup(ev._go_cli_cache.clear)

    def _fake_build(self, builds):
        def build(command, cwd=None, text=None, capture_output=None):
            builds.append(command)
            exe = Path(command[command.index("-o") + 1])
            exe.write_bytes(b"fake")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return build

    def test_go_flow_runner_builds_once_and_reuses(self):
        builds = []
        with patch.object(ev.subprocess, "run", side_effect=self._fake_build(builds)):
            first = ev._go_cli_exe("support-triage")
            second = ev._go_cli_exe("support-triage")
        self.assertEqual(first, second)
        self.assertEqual(len(builds), 1)
        self.assertIn("./internal/m0/cmd", builds[0])
        first.unlink(missing_ok=True)

    def test_go_flow_runner_build_failure_is_a_tooling_error(self):
        def failing_build(*args, **kwargs):
            return type("Completed", (), {
                "returncode": 1, "stdout": "", "stderr": "go: cannot find main module"})()
        with patch.object(ev.subprocess, "run", side_effect=failing_build):
            with self.assertRaises(ev.ToolingError) as caught:
                ev._go_cli_exe("support-triage")
        self.assertIn("go build failed", str(caught.exception))

    def test_go_flow_runner_runs_real_m0_and_m3_cases(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            workdir = Path(directory)
            spec = next(s for s in ev.scenario_cases("support-triage")
                        if s["key"] == "billing-duplicate-charge@model")
            flow = ev.run_flow("support-triage", spec, workdir,
                               languages=("ts", "py", "go"))
            evidence = ev.flow_evidence(flow)
            self.assertEqual(evidence["languages"], ["typescript", "python", "go"])
            self.assertEqual(evidence["result_projection"]["status"], "SUCCEEDED")
            m3spec = next(s for s in ev.scenario_cases("order-brief")
                          if s["key"] == "parallel-out-of-order")
            m3flow = ev.run_flow("order-brief", m3spec, workdir,
                                 languages=("ts", "py", "go"))
            m3evidence = ev.flow_evidence(m3flow)
            self.assertEqual(m3evidence["result_projection"]["status"], "SUCCEEDED")
            self.assertEqual(len(m3evidence["event_sequence"]), 11)

    def test_go_flow_runner_divergence_is_a_tooling_error(self):
        diverged = deepcopy(M0_RESULT)
        diverged["status"] = "FAILED"
        with self.assertRaises(ev.ToolingError) as caught:
            ev.flow_evidence(canned_flow(
                languages=["typescript", "python", "go"], go_result=diverged))
        self.assertIn("typescript and go", str(caught.exception))

    def test_evaluate_languages_flag_semantics(self):
        self.assertEqual(ev.parse_languages(None), ("ts", "py"))
        self.assertEqual(ev.parse_languages("go,ts"), ("ts", "go"))
        with self.assertRaises(ev.ToolingError):
            ev.parse_languages("ts,rust")
        with self.assertRaises(ev.ToolingError):
            ev.parse_languages("")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            def fake_flow(scenario_id, spec, workdir, languages=ev.DEFAULT_LANGUAGES):
                return canned_flow(
                    languages=[ev.LANGUAGE_NAMES[token] for token in languages])
            with patch.object(ev, "GOLDEN_ROOT", Path(directory) / "goldens"), \
                 patch.object(ev, "_git_status", return_value=""), \
                 patch.object(ev, "run_flow", side_effect=fake_flow) as fake:
                ev.regenerate("support-triage", "billing-duplicate-charge@model")
                report = ev.evaluate(["support-triage"],
                                     only_case="billing-duplicate-charge@model")
                self.assertEqual(report["cases"][0]["languages"], ["typescript", "python"])
                self.assertEqual(fake.call_args.kwargs.get("languages"), ("ts", "py"))
                report = ev.evaluate(["support-triage"],
                                     only_case="billing-duplicate-charge@model",
                                     languages=("ts", "py", "go"))
                self.assertEqual(report["cases"][0]["languages"],
                                 ["typescript", "python", "go"])

    def test_go_for_non_go_scenario_is_a_tooling_error(self):
        # --languages go leaves nothing for a non-Go scenario: tooling error.
        self.assertEqual(ev.main(["--scenario", "order-investigation",
                                  "--languages", "go"]), 2)

    def test_non_go_scenarios_forced_down_to_ts_py(self):
        # --all --languages ts,py,go forces M1/M2/M4/M5 to ts,py and runs the
        # showcase pair three-language (the 38-PASS full run's semantics).
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            def fake_flow(scenario_id, spec, workdir, languages=ev.DEFAULT_LANGUAGES):
                return canned_flow(
                    languages=[ev.LANGUAGE_NAMES[token] for token in languages])
            with patch.object(ev, "_git_status", return_value=""), \
                 patch.object(ev, "compare_with_golden", return_value=None), \
                 patch.object(ev, "validate_attribution", return_value=None), \
                 patch.object(ev, "run_flow", side_effect=fake_flow):
                report = ev.evaluate(languages=("ts", "py", "go"))
            by_scenario = {}
            for case in report["cases"]:
                by_scenario.setdefault(case["scenario_id"], set()).add(
                    tuple(case["languages"]))
            self.assertEqual(by_scenario["support-triage"],
                             {("typescript", "python", "go")})
            self.assertEqual(by_scenario["order-brief"],
                             {("typescript", "python", "go")})
            self.assertEqual(by_scenario["order-investigation"],
                             {("typescript", "python")})
            self.assertEqual(by_scenario["order-closure"],
                             {("typescript", "python")})
            self.assertEqual(report["totals"], {"passed": 38, "failed": 0})

    def test_matrix_go_proofs(self):
        from tools import chaos
        rows = chaos.load_matrix()["rows"]
        for row in rows:
            if row["lesson"] in (0, 3):
                self.assertIn("go", row["proof"],
                              f"{row['failure_id']} must carry a Go proof identity")
                self.assertTrue(
                    chaos.proof_identity_exists(row["lesson"], "go", row["proof"]["go"]),
                    f"{row['failure_id']} Go proof missing in the Go suite: "
                    f"{row['proof']['go']}")
            else:
                self.assertNotIn("go", row.get("proof") or {},
                                 f"{row['failure_id']} must stay ts,py-only")

    def test_matrix_go_unit_row_replay(self):
        from tools import chaos
        unit = next(row for row in chaos.load_matrix()["rows"]
                    if row["failure_id"] == "M3-F4")
        report = chaos.replay_matrix(rows=[unit])
        self.assertEqual(report["rows"][0]["status"], "PASS")
