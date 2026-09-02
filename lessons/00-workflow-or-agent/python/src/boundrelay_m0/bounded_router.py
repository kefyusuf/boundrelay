from dataclasses import dataclass
from typing import Mapping

from .schemas import validate_route_decision
from .types import FailureCode, RouteDecision


@dataclass(frozen=True)
class RejectedRoute:
    failure_code: FailureCode
    rejected_route: str | None


def route_decision(raw: object) -> RouteDecision | RejectedRoute:
    validated = validate_route_decision(raw)
    if validated.ok:
        return validated.value
    rejected_route: str | None = None
    if isinstance(raw, Mapping) and isinstance(raw.get("route"), str):
        rejected_route = raw["route"]
    return RejectedRoute("INVALID_ROUTE_DECISION", rejected_route)
