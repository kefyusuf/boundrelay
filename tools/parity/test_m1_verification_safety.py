from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tools.parity.verify_m1 as verifier
from scripts.verify_m1 import clear_previous_evidence, main


class M1VerificationSafetyTests(unittest.TestCase):
    def test_result_is_bound_to_requested_case_mode_and_trace(self) -> None:
        with self.assertRaisesRegex(AssertionError, "wrong case_id"):
            verifier._assert_result_context(
                {"case_id": "other", "mode": "agent", "trace_path": "/tmp/a.jsonl"},
                expected_case_id="agent-delayed-shipment",
                expected_mode="agent",
                expected_trace_path="/tmp/a.jsonl",
                label="sample",
            )
        with self.assertRaisesRegex(AssertionError, "wrong mode"):
            verifier._assert_result_context(
                {"case_id": "agent-delayed-shipment", "mode": "direct", "trace_path": "/tmp/a.jsonl"},
                expected_case_id="agent-delayed-shipment",
                expected_mode="agent",
                expected_trace_path="/tmp/a.jsonl",
                label="sample",
            )
        with self.assertRaisesRegex(AssertionError, "wrong trace_path"):
            verifier._assert_result_context(
                {"case_id": "agent-delayed-shipment", "mode": "agent", "trace_path": "/tmp/b.jsonl"},
                expected_case_id="agent-delayed-shipment",
                expected_mode="agent",
                expected_trace_path="/tmp/a.jsonl",
                label="sample",
            )

    def test_trace_integrity_rejects_wrong_run_id_and_terminal_position(self) -> None:
        with self.assertRaisesRegex(AssertionError, "wrong run_id"):
            verifier._assert_trace_integrity(
                [
                    {"run_id": "run-1", "sequence": 1, "type": "run.created", "source": "python"},
                    {"run_id": "run-2", "sequence": 2, "type": "run.failed", "source": "python"},
                ],
                expected_run_id="run-1",
                expected_source="python",
                label="sample",
                validate_schema=False,
            )
        with self.assertRaisesRegex(AssertionError, "terminal event must be last"):
            verifier._assert_trace_integrity(
                [
                    {"run_id": "run-1", "sequence": 1, "type": "run.failed", "source": "python"},
                    {"run_id": "run-1", "sequence": 2, "type": "model.completed", "source": "python"},
                ],
                expected_run_id="run-1",
                expected_source="python",
                label="sample",
                validate_schema=False,
            )

    def test_unknown_and_invalid_arguments_have_zero_tool_requested(self) -> None:
        verifier._assert_case_behavior(
            case={
                "id": "agent-unknown-tool",
                "mode": "agent",
                "expected_status": "FAILED",
                "expected_failure_code": "UNKNOWN_TOOL",
                "expected_model_steps": 1,
                "expected_tokens_used": 25,
                "expected_tool_invocations": 0,
            },
            result={
                "status": "FAILED",
                "answer": None,
                "failure_code": "UNKNOWN_TOOL",
                "model_steps": 1,
                "tokens_used": 25,
                "tool_invocations": 0,
            },
            events=[
                {"type": "model.requested", "data": {}},
                {"type": "model.completed", "data": {}},
                {"type": "budget.consumed", "data": {}},
                {"type": "run.failed", "data": {
                    "status": "FAILED", "failure_code": "UNKNOWN_TOOL",
                    "model_steps": 1, "tokens_used": 25, "tool_invocations": 0,
                }},
            ],
            label="unknown-tool",
        )

    def test_step_budget_rejects_second_tool_request(self) -> None:
        case = {
            "id": "agent-step-budget", "mode": "agent", "expected_status": "FAILED",
            "expected_failure_code": "STEP_BUDGET_EXCEEDED", "expected_model_steps": 2,
            "expected_tokens_used": 50, "expected_tool_invocations": 1,
        }
        result = {
            "status": "FAILED", "answer": None, "failure_code": "STEP_BUDGET_EXCEEDED",
            "model_steps": 2, "tokens_used": 50, "tool_invocations": 1,
        }
        with self.assertRaisesRegex(AssertionError, "tool.requested"):
            verifier._assert_case_behavior(
                case=case,
                result=result,
                events=[
                    {"type": "tool.requested", "data": {"tool": "lookup_order"}},
                    {"type": "tool.completed", "data": {"tool": "lookup_order"}},
                    {"type": "tool.requested", "data": {"tool": "lookup_shipment"}},
                    {"type": "budget.exceeded", "data": {"budget": "step", "failure_code": "STEP_BUDGET_EXCEEDED"}},
                    {"type": "run.failed", "data": {
                        "status": "FAILED", "failure_code": "STEP_BUDGET_EXCEEDED",
                        "model_steps": 2, "tokens_used": 50, "tool_invocations": 1,
                    }},
                ],
                label="step-budget",
            )

    def test_timeout_and_execution_failure_require_one_failed_event(self) -> None:
        for code in ("TOOL_TIMEOUT", "TOOL_EXECUTION_FAILED"):
            with self.subTest(code=code):
                verifier._assert_case_behavior(
                    case={
                        "id": "case", "mode": "agent", "expected_status": "FAILED",
                        "expected_failure_code": code, "expected_model_steps": 1,
                        "expected_tokens_used": 25, "expected_tool_invocations": 1,
                    },
                    result={
                        "status": "FAILED", "answer": None, "failure_code": code,
                        "model_steps": 1, "tokens_used": 25, "tool_invocations": 1,
                    },
                    events=[
                        {"type": "tool.requested", "data": {"tool": "lookup_order"}},
                        {"type": "tool.failed", "data": {"tool": "lookup_order", "failure_code": code}},
                        {"type": "run.failed", "data": {
                            "status": "FAILED", "failure_code": code,
                            "model_steps": 1, "tokens_used": 25, "tool_invocations": 1,
                        }},
                    ],
                    label=code,
                )

    @patch("tools.parity.verify_m1.subprocess.run")
    def test_cli_stdout_must_contain_exactly_one_json_result(self, run_process) -> None:
        run_process.return_value = subprocess.CompletedProcess(
            ["fake-cli"], 0, stdout='diagnostic\n{"status":"SUCCEEDED"}\n', stderr=""
        )
        with self.assertRaisesRegex(RuntimeError, "exactly one nonblank stdout line"):
            verifier._run(["fake-cli"])

    def test_previous_m1_evidence_is_removed_before_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".boundrelay/m1"
            root.mkdir(parents=True)
            (root / "verification-evidence.json").write_text('{}\n', encoding="utf-8")
            clear_previous_evidence(root)
            self.assertFalse(root.exists())

    @patch("scripts.verify_m1.run")
    @patch("scripts.verify_m1.clear_previous_evidence")
    def test_gate_clears_evidence_before_first_command(self, clear_evidence, run_command) -> None:
        run_command.side_effect = lambda *_args, **_kwargs: self.assertTrue(clear_evidence.called)
        self.assertEqual(main(), 0)
        clear_evidence.assert_called_once_with()
        self.assertEqual(run_command.call_count, 7)

    def test_evidence_records_scenario_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".boundrelay/m1"
            with (
                patch.object(verifier, "OUTPUT_ROOT", output),
                patch.object(verifier, "TRACE_ROOT", output / "traces"),
                patch.object(verifier, "EVIDENCE_PATH", output / "verification-evidence.json"),
                patch.object(verifier, "assert_clean_worktree"),
                patch.object(verifier, "_scenario_cases", return_value=[]),
                patch.object(verifier, "_revision", side_effect=["candidate-sha", "candidate-sha"]),
                patch.object(verifier, "_runtime_version", side_effect=["v24.0.0", "11.0.0"]),
                patch.object(verifier.platform, "python_version", return_value="3.14.0"),
            ):
                evidence = verifier.verify()
        self.assertEqual(evidence["scenario_id"], "order-investigation")
        self.assertEqual(evidence["revision"], "candidate-sha")
        self.assertEqual(evidence["status"], "PASSED")

    def test_passing_evidence_rechecks_same_clean_revision_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / ".boundrelay/m1"
            with (
                patch.object(verifier, "OUTPUT_ROOT", output),
                patch.object(verifier, "TRACE_ROOT", output / "traces"),
                patch.object(verifier, "EVIDENCE_PATH", output / "verification-evidence.json"),
                patch.object(verifier, "assert_clean_worktree") as clean,
                patch.object(verifier, "_scenario_cases", return_value=[]),
                patch.object(verifier, "_revision", side_effect=["candidate-sha", "changed-sha"]),
                patch.object(verifier, "_runtime_version", side_effect=["v24.0.0", "11.0.0"]),
                patch.object(verifier.platform, "python_version", return_value="3.14.0"),
            ):
                with self.assertRaisesRegex(RuntimeError, "revision changed"):
                    verifier.verify()
        self.assertEqual(clean.call_count, 2)

    @patch("tools.parity.verify_m1.subprocess.check_output")
    def test_clean_worktree_is_required(self, check_output) -> None:
        check_output.return_value = " M file.py\n"
        with self.assertRaisesRegex(RuntimeError, "clean Git worktree"):
            verifier.assert_clean_worktree()

    @patch("scripts.verify_m1.run")
    @patch("scripts.verify_m1.clear_previous_evidence")
    def test_gate_command_order_is_canonical(self, clear_evidence, run_command) -> None:
        self.assertEqual(main(), 0)
        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(commands[0][-1], "scripts/verify_m0.py")
        self.assertIn("tools.contracts.test_m1_contracts", commands[1])
        self.assertEqual(commands[2][-2:], ["run", "typecheck"])
        self.assertEqual(commands[3][-1], "test")
        self.assertIn("discover", commands[4])
        self.assertIn("tools.parity.test_m1_verification_safety", commands[5])
        self.assertEqual(commands[6][-1], "tools.parity.verify_m1")


if __name__ == "__main__":
    unittest.main()
