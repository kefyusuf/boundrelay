"""Budget enforcement: SDK max_turns and scripted-usage token accounting.

The step budget is carried by SDK max_turns (loop-top) and re-checked
inside the tools pre-invocation (the M1 checkpoint); the token budget
is checked from the scripted usage at the M1 checkpoint (after the
model turn, before the decision dispatch).
"""
import tempfile
import unittest
from pathlib import Path

from agents import Agent, RunConfig, Runner

from boundrelay_m1_openai import fixtures, mapping


class BudgetCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def test_step_budget_exceeded_pre_tool_invocation(self):
        result = mapping.run_case("agent-step-budget", self.trace)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"], "STEP_BUDGET_EXCEEDED")
        self.assertEqual((result["model_steps"], result["tokens_used"],
                          result["tool_invocations"]), (2, 50, 1))

    def test_token_budget_exceeded_before_decision_dispatch(self):
        result = mapping.run_case("agent-token-budget", self.trace)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"], "TOKEN_BUDGET_EXCEEDED")
        self.assertEqual((result["model_steps"], result["tokens_used"],
                          result["tool_invocations"]), (2, 75, 1))

    def test_direct_mode_consumes_no_budget(self):
        result = mapping.run_case("direct-order-status", self.trace)
        self.assertEqual((result["model_steps"], result["tokens_used"]), (0, 0))
        self.assertEqual(result["tool_invocations"], 1)


class RunLedgerTests(unittest.TestCase):
    def test_model_turn_accounting(self):
        ledger = mapping.RunLedger(max_steps=3, max_tokens=100)
        ledger.record_model_turn(40, 10)
        self.assertFalse(ledger.token_budget_exceeded())
        ledger.record_model_turn(45, 10)
        self.assertTrue(ledger.token_budget_exceeded())
        self.assertEqual((ledger.model_steps, ledger.tokens_used), (2, 105))

    def test_tool_accounting_per_name(self):
        ledger = mapping.RunLedger(max_steps=2, max_tokens=10)
        ledger.record_tool("lookup_order")
        ledger.record_tool("lookup_order")
        ledger.record_tool("lookup_shipment")
        self.assertEqual(ledger.tool_invocations, 3)
        self.assertEqual(ledger.tool_counts,
                         {"lookup_order": 2, "lookup_shipment": 1})
        self.assertEqual(ledger.step_records("agent"),
                         [("model", 0), ("tool.lookup_order", 2),
                          ("tool.lookup_shipment", 1)])
        self.assertEqual(ledger.step_records("direct"),
                         [("tool.lookup_order", 2),
                          ("tool.lookup_shipment", 1)])


class MaxTurnsExceededIntegrationTests(unittest.TestCase):
    """The SDK's own loop-top budget fires and maps to STEP_BUDGET_EXCEEDED.

    Drives the real Runner with max_turns reduced below the case budget,
    so the exception is raised by the SDK itself (not the in-tool check).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def test_sdk_max_turns_maps_to_step_budget_exceeded(self):
        from agents import MaxTurnsExceeded
        case = fixtures.load_case("agent-delayed-shipment")
        ledger = mapping.RunLedger(case.max_steps, case.max_tokens)
        model = mapping.ScriptedAgentModel(list(case.turns), ledger)
        tools = list(mapping.build_function_tools(case, ledger).values())
        agent = Agent(name=mapping.AGENT_NAME,
                      instructions=mapping.AGENT_INSTRUCTIONS,
                      tools=tools, model=model)
        run_config = RunConfig(model=model,
                               model_provider=mapping.ScriptedModelProvider(model),
                               tracing_disabled=True)
        with self.assertRaises(MaxTurnsExceeded) as caught:
            Runner.run_sync(agent, case.request, max_turns=1,
                            run_config=run_config)
        self.assertEqual(ledger.model_steps, 1)
        self.assertEqual(mapping.classify_run_exception(caught.exception),
                         "STEP_BUDGET_EXCEEDED")


class MaxTurnsProbeError(Exception):
    pass


if __name__ == "__main__":
    unittest.main()
