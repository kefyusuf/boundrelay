"""Failure taxonomy: the four tool-boundary codes with exact counters.

UNKNOWN_TOOL is the SDK's own tool-resolution behavior (ModelBehaviorError
"...not found in agent..."); INVALID_TOOL_ARGUMENTS, TOOL_TIMEOUT, and
TOOL_EXECUTION_FAILED are preserved inside the SDK function tools and
propagate because the SDK failure_error_function is disabled.
"""
import tempfile
import unittest
from pathlib import Path

from agents import MaxTurnsExceeded, ModelBehaviorError

from boundrelay_m1_openai import fixtures, mapping


class ToolBoundaryTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def test_unknown_tool_maps_the_sdk_behavior(self):
        result = mapping.run_case("agent-unknown-tool", self.trace)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"], "UNKNOWN_TOOL")
        self.assertEqual((result["model_steps"], result["tokens_used"],
                          result["tool_invocations"]), (1, 25, 0))

    def test_invalid_arguments_fail_before_invocation(self):
        result = mapping.run_case("agent-invalid-arguments", self.trace)
        self.assertEqual(result["failure_code"], "INVALID_TOOL_ARGUMENTS")
        self.assertEqual((result["model_steps"], result["tokens_used"],
                          result["tool_invocations"]), (1, 25, 0))

    def test_declared_tool_timeout(self):
        result = mapping.run_case("agent-tool-timeout", self.trace)
        self.assertEqual(result["failure_code"], "TOOL_TIMEOUT")
        self.assertEqual((result["model_steps"], result["tokens_used"],
                          result["tool_invocations"]), (1, 25, 1))

    def test_declared_tool_execution_failure(self):
        result = mapping.run_case("agent-tool-failure", self.trace)
        self.assertEqual(result["failure_code"], "TOOL_EXECUTION_FAILED")
        self.assertEqual((result["model_steps"], result["tokens_used"],
                          result["tool_invocations"]), (1, 25, 1))

    def test_failed_results_carry_no_answer(self):
        for key in ("agent-unknown-tool", "agent-invalid-arguments",
                    "agent-tool-timeout", "agent-tool-failure"):
            with self.subTest(case=key):
                result = mapping.run_case(key, self.trace)
                self.assertIsNone(result["answer"])


class ClassifyTests(unittest.TestCase):
    """Direct proofs of the SDK-behavior mapping (D-008 question 2)."""

    def test_sdk_unknown_tool_error_maps_to_unknown_tool(self):
        error = ModelBehaviorError(
            "Tool lookup_customer not found in agent boundrelay-m1-order-investigator")
        self.assertEqual(mapping.classify_run_exception(error), "UNKNOWN_TOOL")

    def test_max_turns_exceeded_maps_to_step_budget(self):
        self.assertEqual(
            mapping.classify_run_exception(MaxTurnsExceeded("Max turns (2) exceeded")),
            "STEP_BUDGET_EXCEEDED")

    def test_sdk_wrapped_tool_failures_resolve_through_the_cause_chain(self):
        wrapped = None
        try:
            try:
                raise mapping.ToolTimeoutFailure("lookup_order timed out")
            except mapping.ToolTimeoutFailure as inner:
                raise RuntimeError("Error running tool lookup_order") from inner
        except RuntimeError as error:
            wrapped = error
        self.assertEqual(mapping.classify_run_exception(wrapped), "TOOL_TIMEOUT")

    def test_unmapped_sdk_errors_classify_as_none(self):
        self.assertIsNone(mapping.classify_run_exception(ValueError("boom")))
        plain = ModelBehaviorError("Model did not produce a final response!")
        self.assertIsNone(mapping.classify_run_exception(plain))

    def test_mapping_failures_carry_taxonomy_codes(self):
        for failure, code in (
                (mapping.UnknownToolFailure("x"), "UNKNOWN_TOOL"),
                (mapping.InvalidToolArgumentsFailure("x"), "INVALID_TOOL_ARGUMENTS"),
                (mapping.ToolTimeoutFailure("x"), "TOOL_TIMEOUT"),
                (mapping.ToolExecutionFailure("x"), "TOOL_EXECUTION_FAILED"),
                (mapping.StepBudgetExceededFailure("x"), "STEP_BUDGET_EXCEEDED"),
                (mapping.TokenBudgetExceededFailure("x"), "TOKEN_BUDGET_EXCEEDED")):
            with self.subTest(code=code):
                self.assertEqual(failure.failure_code, code)


if __name__ == "__main__":
    unittest.main()
