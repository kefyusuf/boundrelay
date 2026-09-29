from pathlib import Path
import tempfile
import unittest

from boundrelay_m1.scenario import find_scenario_case, load_scenario
from boundrelay_m1.scripted_model import ScriptedModelError, ScriptedModelProvider


class ScenarioTests(unittest.IsolatedAsyncioTestCase):
    def test_loads_canonical_agent_case_without_coercion(self) -> None:
        scenario = load_scenario()
        case = find_scenario_case(scenario, "agent-delayed-shipment")
        self.assertEqual(scenario.scenario_id, "order-investigation")
        self.assertEqual(case.mode, "agent")
        self.assertEqual(case.max_steps, 3)
        self.assertEqual(case.max_tokens, 129)
        self.assertEqual(case.expected_model_steps, 3)
        self.assertEqual(case.expected_tokens_used, 129)

    def test_rejects_unknown_case_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown scenario case"):
            find_scenario_case(load_scenario(), "missing-case")

    def test_rejects_malformed_integer_instead_of_coercing(self) -> None:
        content = """schema_version: \"1.0\"
scenario_id: order-investigation
cases:
  - id: bad-case
    mode: agent
    request: bad
    max_steps: \"3\"
    max_tokens: 10
    expected_status: FAILED
    expected_failure_code: UNKNOWN_TOOL
    expected_model_steps: 1
    expected_tokens_used: 1
    expected_tool_invocations: 0
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "max_steps"):
                load_scenario(path)

    async def test_scripted_model_rejects_out_of_order_turn(self) -> None:
        provider = ScriptedModelProvider.from_file()
        with self.assertRaises(ScriptedModelError):
            await provider.next_turn(
                case_id="agent-delayed-shipment",
                request="Why is order ORD-1001 delayed?",
                model_step=2,
                observations=(),
            )

    async def test_scripted_model_rejects_trajectory_exhaustion(self) -> None:
        provider = ScriptedModelProvider.from_file()
        for step in (1, 2, 3):
            await provider.next_turn(
                case_id="agent-delayed-shipment",
                request="Why is order ORD-1001 delayed?",
                model_step=step,
                observations=(),
            )
        with self.assertRaises(ScriptedModelError):
            await provider.next_turn(
                case_id="agent-delayed-shipment",
                request="Why is order ORD-1001 delayed?",
                model_step=4,
                observations=(),
            )


if __name__ == "__main__":
    unittest.main()
