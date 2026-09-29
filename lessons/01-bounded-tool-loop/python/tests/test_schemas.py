import unittest

from boundrelay_m1.schemas import (
    validate_model_turn,
    validate_run_result,
    validate_tool_arguments,
)


class SchemaTests(unittest.TestCase):
    def test_unknown_tool_name_is_structurally_valid_at_outer_model_boundary(self) -> None:
        unknown_turn = {
            "schema_version": "1.0",
            "decision": {
                "kind": "tool_call",
                "call_id": "call-1",
                "tool": "unknown-tool",
                "arguments": {},
            },
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }
        self.assertTrue(validate_model_turn(unknown_turn).ok)

    def test_tool_argument_schemas_enforce_identifiers_and_extra_properties(self) -> None:
        self.assertTrue(validate_tool_arguments("lookup_order", {"order_id": "ORD-1001"}).ok)
        self.assertFalse(validate_tool_arguments("lookup_order", {"order_id": "1001"}).ok)
        self.assertFalse(validate_tool_arguments("lookup_order", {"order_id": "ORD-1001", "extra": True}).ok)
        self.assertTrue(validate_tool_arguments("lookup_shipment", {"shipment_id": "SHP-1001"}).ok)

    def test_canonical_success_result_validates(self) -> None:
        result = {
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
        self.assertTrue(validate_run_result(result).ok)


if __name__ == "__main__":
    unittest.main()
