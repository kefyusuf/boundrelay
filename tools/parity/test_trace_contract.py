from copy import deepcopy
import unittest

import tools.parity.verify_m0 as verifier


def event(event_type: str, data: dict[str, object] | None = None) -> dict[str, object]:
    return {"type": event_type, "data": data or {}}


class TraceContractTests(unittest.TestCase):
    def require_helper(self, name: str):
        helper = getattr(verifier, name, None)
        if not callable(helper):
            self.fail(f"verify_m0 must expose {name}")
        return helper

    def test_requires_the_canonical_lifecycle_sequence_for_each_m0_path(self) -> None:
        assert_sequence = self.require_helper("_assert_lifecycle_sequence")
        canonical = {
            ("deterministic", "SUCCEEDED"): [
                "run.created",
                "run.started",
                "step.started",
                "route.selected",
                "step.completed",
                "step.started",
                "step.completed",
                "run.completed",
            ],
            ("model", "SUCCEEDED"): [
                "run.created",
                "run.started",
                "step.started",
                "model.requested",
                "model.completed",
                "route.selected",
                "step.completed",
                "step.started",
                "step.completed",
                "run.completed",
            ],
            ("model", "FAILED"): [
                "run.created",
                "run.started",
                "step.started",
                "model.requested",
                "model.completed",
                "route.rejected",
                "step.failed",
                "run.failed",
            ],
        }

        for (mode, status), event_types in canonical.items():
            with self.subTest(mode=mode, status=status):
                assert_sequence(
                    [event(event_type) for event_type in event_types],
                    mode=mode,
                    expected_status=status,
                    label=f"{mode}/{status}",
                )

        incomplete = [event(event_type) for event_type in canonical[("model", "SUCCEEDED")]]
        del incomplete[1]
        with self.assertRaisesRegex(AssertionError, "event sequence"):
            assert_sequence(
                incomplete,
                mode="model",
                expected_status="SUCCEEDED",
                label="model/SUCCEEDED",
            )

    def test_binds_lifecycle_context_and_classify_steps_to_the_requested_case(self) -> None:
        assert_context = self.require_helper("_assert_trace_context")
        valid = [
            event("run.created", {
                "scenario_id": "support-triage",
                "case_id": "billing-duplicate-charge",
                "mode": "model",
            }),
            event("run.started", {
                "case_id": "billing-duplicate-charge",
                "mode": "model",
            }),
            event("step.started", {"step": "classify"}),
            event("model.requested", {"case_id": "billing-duplicate-charge"}),
            event("model.completed", {
                "case_id": "billing-duplicate-charge",
                "decision": {"route": "billing", "confidence": 0.98},
            }),
            event("step.completed", {"step": "classify", "route": "billing"}),
        ]

        assert_context(
            valid,
            expected_case_id="billing-duplicate-charge",
            expected_mode="model",
            label="Python billing/model",
        )

        for field in ("scenario_id", "case_id", "mode"):
            with self.subTest(event="run.created", field=field):
                invalid = deepcopy(valid)
                invalid[0]["data"][field] = "wrong"
                with self.assertRaisesRegex(AssertionError, "run.created"):
                    assert_context(
                        invalid,
                        expected_case_id="billing-duplicate-charge",
                        expected_mode="model",
                        label="Python billing/model",
                    )

        for field in ("case_id", "mode"):
            with self.subTest(event="run.started", field=field):
                invalid = deepcopy(valid)
                invalid[1]["data"][field] = "wrong"
                with self.assertRaisesRegex(AssertionError, "run.started"):
                    assert_context(
                        invalid,
                        expected_case_id="billing-duplicate-charge",
                        expected_mode="model",
                        label="Python billing/model",
                    )

        for index in (2, 5):
            with self.subTest(classify_event=index):
                invalid = deepcopy(valid)
                invalid[index]["data"]["step"] = "specialist.billing"
                with self.assertRaisesRegex(AssertionError, "classify"):
                    assert_context(
                        invalid,
                        expected_case_id="billing-duplicate-charge",
                        expected_mode="model",
                        label="Python billing/model",
                    )

        for index in (3, 4):
            with self.subTest(model_event=index):
                invalid = deepcopy(valid)
                invalid[index]["data"]["case_id"] = "wrong-case"
                with self.assertRaisesRegex(AssertionError, "wrong case_id"):
                    assert_context(
                        invalid,
                        expected_case_id="billing-duplicate-charge",
                        expected_mode="model",
                        label="Python billing/model",
                    )


if __name__ == "__main__":
    unittest.main()
