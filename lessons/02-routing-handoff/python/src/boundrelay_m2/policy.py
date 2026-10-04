from .types import ReceiverName, Route, RouteDecision, RouteSelection

BILLING_KEYWORDS = ("charged", "charge", "invoice", "payment", "refund", "billed")
TECHNICAL_KEYWORDS = ("error", "crash", "cannot log in", "can't log in", "bug", "broken")
RECEIVERS: dict[Route, ReceiverName] = {
    "billing": "billing-specialist",
    "technical": "technical-specialist",
    "general": "general-specialist",
}
CONFIDENCE_THRESHOLD = 0.80


def classify_with_code(request: str) -> RouteDecision:
    value = request.lower()
    if any(keyword in value for keyword in BILLING_KEYWORDS):
        return RouteDecision("billing", 1.0)
    if any(keyword in value for keyword in TECHNICAL_KEYWORDS):
        return RouteDecision("technical", 1.0)
    return RouteDecision("general", 1.0)


def apply_confidence_policy(decision: RouteDecision) -> RouteSelection:
    fallback_applied = decision.confidence < CONFIDENCE_THRESHOLD
    selected_route: Route = "general" if fallback_applied else decision.route
    return RouteSelection(
        proposed_route=decision.route,
        selected_route=selected_route,
        confidence=decision.confidence,
        policy_outcome="fallback" if fallback_applied else "selected",
        fallback_applied=fallback_applied,
        receiver=RECEIVERS[selected_route],
    )
