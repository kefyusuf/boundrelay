import unittest

from boundrelay_m2.policy import apply_confidence_policy, classify_with_code
from boundrelay_m2.types import RouteDecision


class PolicyTests(unittest.TestCase):
    def test_equality_at_080_keeps_proposed_route(self) -> None:
        selection = apply_confidence_policy(RouteDecision("billing", 0.80))
        self.assertEqual(selection.proposed_route, "billing")
        self.assertEqual(selection.selected_route, "billing")
        self.assertEqual(selection.receiver, "billing-specialist")
        self.assertEqual(selection.policy_outcome, "selected")
        self.assertFalse(selection.fallback_applied)

    def test_079_falls_back_to_general(self) -> None:
        selection = apply_confidence_policy(RouteDecision("billing", 0.79))
        self.assertEqual(selection.proposed_route, "billing")
        self.assertEqual(selection.selected_route, "general")
        self.assertEqual(selection.receiver, "general-specialist")
        self.assertEqual(selection.policy_outcome, "fallback")
        self.assertTrue(selection.fallback_applied)

    def test_maps_all_routes_to_fixed_receivers(self) -> None:
        self.assertEqual(apply_confidence_policy(RouteDecision("billing", 0.95)).receiver, "billing-specialist")
        self.assertEqual(apply_confidence_policy(RouteDecision("technical", 0.95)).receiver, "technical-specialist")
        self.assertEqual(apply_confidence_policy(RouteDecision("general", 0.95)).receiver, "general-specialist")

    def test_copies_accepted_deterministic_keyword_baseline(self) -> None:
        self.assertEqual(classify_with_code("I was charged twice"), RouteDecision("billing", 1.0))
        self.assertEqual(classify_with_code("The app shows an error"), RouteDecision("technical", 1.0))
        self.assertEqual(classify_with_code("What are your opening hours?"), RouteDecision("general", 1.0))


if __name__ == "__main__":
    unittest.main()
