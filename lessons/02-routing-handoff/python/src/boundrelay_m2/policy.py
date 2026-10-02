from .types import RouteDecision, RouteSelection

ROUTE_RECEIVERS = {'billing': 'billing-specialist', 'technical': 'technical-specialist', 'general': 'general-specialist'}


def apply_confidence_policy(decision: RouteDecision) -> RouteSelection:
    fallback = decision.confidence < .80
    selected = 'general' if fallback else decision.route
    return RouteSelection(decision.route, selected, decision.confidence, 'fallback' if fallback else 'selected', fallback, ROUTE_RECEIVERS[selected])
