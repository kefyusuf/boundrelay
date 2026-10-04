import unittest

from boundrelay_m2.schemas import (
    validate_handoff,
    validate_route_decision,
    validate_run_event,
    validate_run_result,
)


class SchemaTests(unittest.TestCase):
    def test_reuses_m0_route_decision_boundary(self) -> None:
        self.assertTrue(validate_route_decision({"route": "billing", "confidence": 0.80}).ok)
        self.assertFalse(validate_route_decision({"route": "unknown", "confidence": 0.80}).ok)
        self.assertFalse(
            validate_route_decision(
                {"route": "billing", "confidence": 0.80, "receiver": "billing-specialist"}
            ).ok
        )

    def test_handoff_requires_minimum_receiver_context_and_rejects_extras(self) -> None:
        valid = {
            "schema_version": "1.0",
            "handoff_id": "handoff-1",
            "sender": "support-router",
            "receiver": "billing-specialist",
            "sender_intent": {"route": "billing", "confidence": 1.0, "policy_outcome": "selected"},
            "receiver_input": {"ticket_id": "TCK-1001", "request_text": "I was charged twice."},
        }
        self.assertTrue(validate_handoff(valid).ok)
        self.assertFalse(
            validate_handoff({**valid, "receiver_input": {"ticket_id": "TCK-1001"}}).ok
        )
        self.assertFalse(
            validate_handoff(
                {
                    **valid,
                    "receiver_input": {
                        **valid["receiver_input"],
                        "model_prompt": "must not cross handoff boundary",
                    },
                }
            ).ok
        )

    def test_canonical_success_result_validates(self) -> None:
        result = {
            "schema_version": "1.0",
            "run_id": "run-1",
            "scenario_id": "support-handoff",
            "case_id": "code-billing-handoff",
            "router_mode": "code",
            "status": "SUCCEEDED",
            "proposed_route": "billing",
            "selected_route": "billing",
            "receiver": "billing-specialist",
            "fallback_applied": False,
            "specialist_invoked": True,
            "failure_code": None,
            "trace_path": ".boundrelay/m2/trace.jsonl",
        }
        self.assertTrue(validate_run_result(result).ok)

    def test_event_validator_accepts_handoff_family(self) -> None:
        event = {
            "schema_version": "1.0",
            "event_id": "evt-1",
            "run_id": "run-1",
            "sequence": 1,
            "type": "handoff.requested",
            "timestamp": "2026-09-30T00:00:00Z",
            "source": "python",
            "data": {},
        }
        self.assertTrue(validate_run_event(event).ok)


if __name__ == "__main__":
    unittest.main()
