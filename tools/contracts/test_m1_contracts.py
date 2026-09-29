import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "fixtures/scenarios/order-investigation.yaml"
FAKE_MODEL = ROOT / "fixtures/fake-model/order-investigation.yaml"
FAKE_TOOLS = ROOT / "fixtures/fake-tools/order-investigation.yaml"
INVARIANTS = ROOT / "lessons/01-bounded-tool-loop/invariants.yaml"
MODEL_TURN_SCHEMA = ROOT / "contracts/agent/model-turn.schema.json"
LOOKUP_ORDER_SCHEMA = ROOT / "contracts/tools/lookup-order-arguments.schema.json"
LOOKUP_SHIPMENT_SCHEMA = ROOT / "contracts/tools/lookup-shipment-arguments.schema.json"
RESULT_SCHEMA = ROOT / "contracts/results/tool-loop-result.schema.json"
EVENT_SCHEMA = ROOT / "contracts/events/run-event.schema.json"

EXPECTED_CASES = {
    "direct-order-status",
    "agent-delayed-shipment",
    "agent-unknown-tool",
    "agent-invalid-arguments",
    "agent-tool-timeout",
    "agent-tool-failure",
    "agent-step-budget",
    "agent-token-budget",
}


def load_yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected YAML object: {path}")
    return value


def schema_errors(path: Path, value: object):
    schema = json.loads(path.read_text(encoding="utf-8"))
    return list(Draft202012Validator(schema).iter_errors(value))


class M1ContractTests(unittest.TestCase):
    def test_m1_case_set_and_success_boundaries(self) -> None:
        scenario = load_yaml(SCENARIO)
        cases = {case["id"]: case for case in scenario["cases"]}
        self.assertEqual(scenario["schema_version"], "1.0")
        self.assertEqual(scenario["scenario_id"], "order-investigation")
        self.assertEqual(set(cases), EXPECTED_CASES)
        self.assertEqual(cases["direct-order-status"]["mode"], "direct")
        self.assertEqual(cases["direct-order-status"]["max_steps"], 0)
        self.assertEqual(cases["direct-order-status"]["max_tokens"], 0)
        self.assertEqual(cases["agent-delayed-shipment"]["max_steps"], 3)
        self.assertEqual(cases["agent-delayed-shipment"]["max_tokens"], 129)
        self.assertEqual(cases["agent-delayed-shipment"]["expected_model_steps"], 3)
        self.assertEqual(cases["agent-delayed-shipment"]["expected_tokens_used"], 129)
        self.assertEqual(cases["agent-delayed-shipment"]["expected_tool_invocations"], 2)
        self.assertEqual(
            cases["direct-order-status"]["expected_answer"],
            "Order ORD-1001 status is SHIPPED.",
        )
        self.assertEqual(
            cases["agent-delayed-shipment"]["expected_answer"],
            "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
        )

    def test_budget_failures_preserve_one_prior_dispatch(self) -> None:
        scenario = load_yaml(SCENARIO)
        cases = {case["id"]: case for case in scenario["cases"]}
        self.assertEqual(cases["agent-step-budget"]["expected_tool_invocations"], 1)
        self.assertEqual(cases["agent-token-budget"]["expected_tool_invocations"], 1)
        self.assertEqual(cases["agent-step-budget"]["expected_failure_code"], "STEP_BUDGET_EXCEEDED")
        self.assertEqual(cases["agent-token-budget"]["expected_failure_code"], "TOKEN_BUDGET_EXCEEDED")

    def test_fixture_sets_are_complete_and_ordered(self) -> None:
        model = load_yaml(FAKE_MODEL)
        tools = load_yaml(FAKE_TOOLS)
        scenario = load_yaml(SCENARIO)
        agent_cases = {case["id"] for case in scenario["cases"] if case["mode"] == "agent"}
        self.assertEqual(set(model["trajectories"]), agent_cases)
        self.assertEqual(len(model["trajectories"]["agent-delayed-shipment"]), 3)
        self.assertEqual(
            [turn["return"]["decision"]["tool"] for turn in model["trajectories"]["agent-delayed-shipment"][:2]],
            ["lookup_order", "lookup_shipment"],
        )
        self.assertEqual(tools["orders"]["ORD-9001"]["behavior"], "timeout")
        self.assertEqual(tools["orders"]["ORD-9002"]["behavior"], "failure")
        self.assertEqual(tools["shipments"]["SHP-1001"]["output"]["reason"], "WEATHER")

    def test_new_schemas_accept_and_reject_exact_boundaries(self) -> None:
        unknown_tool_turn = {
            "schema_version": "1.0",
            "decision": {
                "kind": "tool_call",
                "call_id": "call-1",
                "tool": "unknown-but-structurally-valid",
                "arguments": {},
            },
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }
        self.assertEqual(schema_errors(MODEL_TURN_SCHEMA, unknown_tool_turn), [])
        self.assertNotEqual(schema_errors(LOOKUP_ORDER_SCHEMA, {"order_id": "1001"}), [])
        self.assertNotEqual(
            schema_errors(LOOKUP_ORDER_SCHEMA, {"order_id": "ORD-1001", "extra": True}),
            [],
        )
        self.assertEqual(schema_errors(LOOKUP_ORDER_SCHEMA, {"order_id": "ORD-1001"}), [])
        self.assertEqual(schema_errors(LOOKUP_SHIPMENT_SCHEMA, {"shipment_id": "SHP-1001"}), [])

    def test_result_schema_encodes_success_and_failure(self) -> None:
        success = {
            "schema_version": "1.0",
            "run_id": "run-1",
            "scenario_id": "order-investigation",
            "case_id": "agent-delayed-shipment",
            "mode": "agent",
            "status": "SUCCEEDED",
            "answer": "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
            "failure_code": None,
            "model_steps": 3,
            "tokens_used": 129,
            "tool_invocations": 2,
            "trace_path": ".boundrelay/m1/trace.jsonl",
        }
        failure = dict(success)
        failure.update({
            "case_id": "agent-unknown-tool",
            "status": "FAILED",
            "answer": None,
            "failure_code": "UNKNOWN_TOOL",
            "model_steps": 1,
            "tokens_used": 25,
            "tool_invocations": 0,
        })
        invalid = dict(failure)
        invalid["answer"] = "must be null on failure"
        self.assertEqual(schema_errors(RESULT_SCHEMA, success), [])
        self.assertEqual(schema_errors(RESULT_SCHEMA, failure), [])
        self.assertNotEqual(schema_errors(RESULT_SCHEMA, invalid), [])

    def test_event_schema_remains_m0_compatible_and_accepts_m1_types(self) -> None:
        base_event = {
            "schema_version": "1.0",
            "event_id": "evt-1",
            "run_id": "run-1",
            "sequence": 1,
            "timestamp": "2026-09-29T00:00:00Z",
            "source": "python",
            "data": {},
        }
        m0_event = dict(base_event, type="route.selected")
        m1_event = dict(base_event, type="tool.requested")
        self.assertEqual(schema_errors(EVENT_SCHEMA, m0_event), [])
        self.assertEqual(schema_errors(EVENT_SCHEMA, m1_event), [])

    def test_schema_declarations_and_invariant_set_are_valid(self) -> None:
        for schema_path in (
            MODEL_TURN_SCHEMA,
            LOOKUP_ORDER_SCHEMA,
            LOOKUP_SHIPMENT_SCHEMA,
            RESULT_SCHEMA,
            EVENT_SCHEMA,
        ):
            Draft202012Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))

        invariants = load_yaml(INVARIANTS)
        ids = [item["id"] for item in invariants["invariants"]]
        self.assertEqual(ids, [f"M1-I{number:02d}" for number in range(1, 15)])

        scenario = load_yaml(SCENARIO)
        for case in scenario["cases"]:
            self.assertEqual(case["expected_status"], "SUCCEEDED" if "expected_answer" in case else "FAILED")
            self.assertEqual(
                int("expected_answer" in case) + int("expected_failure_code" in case),
                1,
                case["id"],
            )


if __name__ == "__main__":
    unittest.main()
