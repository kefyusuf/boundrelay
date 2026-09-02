from .types import RouteDecision

_BILLING_KEYWORDS = ("charged", "charge", "invoice", "payment", "refund", "billed")
_TECHNICAL_KEYWORDS = ("error", "crash", "cannot log in", "can't log in", "bug", "broken")


def classify_deterministically(request: str) -> RouteDecision:
    value = request.lower()
    if any(keyword in value for keyword in _BILLING_KEYWORDS):
        return RouteDecision("billing", 1.0)
    if any(keyword in value for keyword in _TECHNICAL_KEYWORDS):
        return RouteDecision("technical", 1.0)
    return RouteDecision("general", 1.0)
