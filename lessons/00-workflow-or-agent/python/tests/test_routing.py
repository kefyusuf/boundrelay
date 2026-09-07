import unittest

from boundrelay_m0.bounded_router import RejectedRoute, route_decision
from boundrelay_m0.deterministic_router import classify_deterministically
from boundrelay_m0.types import RouteDecision


class RoutingTests(unittest.TestCase):
    def test_classifies_the_three_deterministic_support_routes(self) -> None:
        self.assertEqual(classify_deterministically("I was charged twice"), RouteDecision("billing", 1.0))
        self.assertEqual(classify_deterministically("The app shows an error"), RouteDecision("technical", 1.0))
        self.assertEqual(classify_deterministically("What are your hours?"), RouteDecision("general", 1.0))

    def test_rejects_an_unknown_model_route_before_dispatch(self) -> None:
        self.assertEqual(
            route_decision({"route": "unknown-specialist", "confidence": 0.99}),
            RejectedRoute("INVALID_ROUTE_DECISION", "unknown-specialist"),
        )


if __name__ == "__main__":
    unittest.main()
