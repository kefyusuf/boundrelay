"""M2 taxonomy through the ADK machinery: zero-dispatch failures, the
0.80 confidence policy re-established inside the mapping, and the
closed decision validation."""
import tempfile
import unittest
from pathlib import Path

from boundrelay_m2_adk import fixtures, mapping


class PolicyTests(unittest.TestCase):
    def test_code_classifier_is_deterministic(self):
        self.assertEqual(
            mapping.classify_with_code("I was charged twice for invoice INV-1001."),
            {"route": "billing", "confidence": 1.0})
        self.assertEqual(
            mapping.classify_with_code("The app keeps crashing with an error."),
            {"route": "technical", "confidence": 1.0})
        self.assertEqual(
            mapping.classify_with_code("What is your address?"),
            {"route": "general", "confidence": 1.0})

    def test_confidence_policy_fallback_boundary(self):
        at = lambda confidence: mapping.apply_confidence_policy(
            {"route": "technical", "confidence": confidence})
        self.assertFalse(at(0.81)["fallback_applied"])
        self.assertFalse(at(0.80)["fallback_applied"])
        self.assertTrue(at(0.79)["fallback_applied"])
        fallback = at(0.54)
        self.assertEqual(fallback["selected_route"], "general")
        self.assertEqual(fallback["receiver"], "general-specialist")
        self.assertEqual(fallback["policy_outcome"], "fallback")


class FallbackBoundaryParityTests(unittest.TestCase):
    """0.79 / 0.80 / 0.81 replayed through the real ADK machinery."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def _run(self, confidence):
        return mapping.run_case("model-technical-handoff", self.trace,
                                decision={"route": "technical",
                                          "confidence": confidence})

    def test_0_81_is_selected(self):
        result = self._run(0.81)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertFalse(result["fallback_applied"])
        self.assertEqual(result["selected_route"], "technical")
        self.assertEqual(result["receiver"], "technical-specialist")

    def test_0_80_is_selected(self):
        result = self._run(0.80)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertFalse(result["fallback_applied"])

    def test_0_79_falls_back_to_general(self):
        result = self._run(0.79)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertTrue(result["fallback_applied"])
        self.assertEqual(result["proposed_route"], "technical")
        self.assertEqual(result["selected_route"], "general")
        self.assertEqual(result["receiver"], "general-specialist")
        self.assertEqual([step["step_name"]
                          for step in result["attribution"]["steps"]],
                         ["classify", "receiver.general-specialist"])


class InvalidRouteDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def _run(self, decision):
        return mapping.run_case("model-technical-handoff", self.trace,
                                decision=decision)

    def test_unknown_route_is_rejected_with_zero_dispatch(self):
        result = self._run({"route": "unknown", "confidence": 0.9})
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"], "INVALID_ROUTE_DECISION")
        self.assertIsNone(result["proposed_route"])
        self.assertIsNone(result["selected_route"])
        self.assertIsNone(result["receiver"])
        self.assertFalse(result["fallback_applied"])
        self.assertFalse(result["specialist_invoked"])
        self.assertEqual([step["step_name"]
                          for step in result["attribution"]["steps"]],
                         ["classify"])

    def test_out_of_range_confidence_is_rejected(self):
        result = self._run({"route": "technical", "confidence": 1.5})
        self.assertEqual(result["failure_code"], "INVALID_ROUTE_DECISION")

    def test_extra_decision_fields_are_rejected(self):
        result = self._run({"route": "technical", "confidence": 0.9,
                            "reason": "because"})
        self.assertEqual(result["failure_code"], "INVALID_ROUTE_DECISION")


class ZeroDispatchTests(unittest.TestCase):
    """The two handoff failures dispatch zero receivers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def test_context_loss_never_dispatches(self):
        result = mapping.run_case("handoff-context-loss", self.trace)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"], "HANDOFF_CONTEXT_INVALID")
        self.assertFalse(result["specialist_invoked"])
        self.assertEqual([step["step_name"]
                          for step in result["attribution"]["steps"]],
                         ["classify"])

    def test_receiver_unavailable_never_dispatches(self):
        result = mapping.run_case("handoff-receiver-unavailable", self.trace)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_code"],
                         "HANDOFF_RECEIVER_UNAVAILABLE")
        self.assertFalse(result["specialist_invoked"])
        self.assertEqual([step["step_name"]
                          for step in result["attribution"]["steps"]],
                         ["classify"])


class HandoffBoundaryTests(unittest.TestCase):
    """Direct proofs at the handoff boundary (spy receivers)."""

    def setUp(self):
        self.case = fixtures.load_case("code-billing-handoff")
        self.ledger = mapping.RunLedger()
        self.ledger.count_classify()
        self.dispatched = []

    def _spy_directory(self, names=fixtures.RECEIVER_NAMES):
        directory = {}
        for name in names:
            directory[name] = (lambda name_=name: (
                lambda receiver_input: self.dispatched.append(
                    (name_, dict(receiver_input)))))()
        return directory

    def _run_boundary(self, case, directory):
        return mapping.execute_handoff(
            {"route": "billing", "confidence": 1.0}, case, self.ledger,
            directory)

    def test_success_dispatches_once_with_the_receiver_input(self):
        ack = self._run_boundary(self.case, self._spy_directory())
        self.assertEqual(ack["dispatched"], True)
        self.assertEqual(len(self.dispatched), 1)
        name, receiver_input = self.dispatched[0]
        self.assertEqual(name, "billing-specialist")
        self.assertEqual(receiver_input,
                         {"ticket_id": "TCK-1001",
                          "request_text": self.case.request})
        self.assertEqual(self.ledger.step_records("code"),
                         [("classify", 1), ("receiver.billing-specialist", 1)])

    def test_missing_receiver_is_unavailable_before_dispatch(self):
        directory = self._spy_directory(names=("general-specialist",))
        with self.assertRaises(mapping.HandoffReceiverUnavailableFailure):
            self._run_boundary(self.case, directory)
        self.assertEqual(self.dispatched, [])

    def test_invalid_context_is_rejected_before_dispatch(self):
        case = fixtures.load_case("model-technical-handoff")
        case.failure = {"omit_receiver_input_fields": ("ticket_id",)}
        with self.assertRaises(mapping.HandoffContextInvalidFailure):
            mapping.execute_handoff({"route": "technical",
                                     "confidence": 0.92}, case, self.ledger,
                                    self._spy_directory())
        self.assertEqual(self.dispatched, [])

    def test_fixture_driven_context_loss_is_rejected(self):
        case = fixtures.load_case("handoff-context-loss")
        with self.assertRaises(mapping.HandoffContextInvalidFailure):
            mapping.execute_handoff({"route": "billing",
                                     "confidence": 0.93}, case, self.ledger,
                                    self._spy_directory())
        self.assertEqual(self.dispatched, [])

    def test_invalid_decision_is_rejected_before_selection(self):
        with self.assertRaises(mapping.InvalidRouteDecisionFailure):
            mapping.execute_handoff({"route": "unknown", "confidence": 1.0},
                                    self.case, self.ledger,
                                    self._spy_directory())
        self.assertEqual(self.dispatched, [])
        self.assertIsNone(self.ledger.selection)


class ClassifyRunExceptionTests(unittest.TestCase):
    def test_mapped_failures_resolve_to_their_codes(self):
        for failure_type, code in (
                (mapping.InvalidRouteDecisionFailure,
                 "INVALID_ROUTE_DECISION"),
                (mapping.HandoffContextInvalidFailure,
                 "HANDOFF_CONTEXT_INVALID"),
                (mapping.HandoffReceiverUnavailableFailure,
                 "HANDOFF_RECEIVER_UNAVAILABLE")):
            self.assertEqual(mapping.classify_run_exception(failure_type("x")),
                             code)

    def test_unmapped_exceptions_do_not_classify(self):
        self.assertIsNone(mapping.classify_run_exception(RuntimeError("x")))
        self.assertIsNone(mapping.classify_run_exception(Exception("x")))


if __name__ == "__main__":
    unittest.main()
