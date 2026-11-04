from pathlib import Path
from typing import Mapping, cast

import yaml

from .paths import SCENARIO_PATH
from .attribution import STEP_KINDS
from .types import (
    FailureCode,
    ROUTES,
    Route,
    ScenarioCase,
    ScenarioDefinition,
    ScenarioFailureCase,
    ScenarioSuccessCase,
)


def _is_route(value: object) -> bool:
    return isinstance(value, str) and value in ROUTES


def _parse_case(raw: object) -> ScenarioCase:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("request"), str):
        raise ValueError("Scenario case must define string id and request fields.")
    case_id = cast(str, raw["id"])
    request = cast(str, raw["request"])
    expected_route = raw.get("expected_route")
    expected_failure = raw.get("expected_failure_code")

    if _is_route(expected_route) and expected_failure is None:
        return ScenarioSuccessCase(case_id, request, cast(Route, expected_route))
    if expected_route is None and expected_failure == "INVALID_ROUTE_DECISION":
        return ScenarioFailureCase(case_id, request, cast(FailureCode, expected_failure))
    raise ValueError(f"Scenario case {case_id} must define exactly one supported expectation.")


def parse_attribution(raw: object) -> dict[str, object] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"latency_ms", "price_table"}:
        raise ValueError("Invalid attribution tables.")
    latency, prices = raw["latency_ms"], raw["price_table"]
    if not isinstance(latency, Mapping) or not latency or any(
        not key or type(value) is not int or value < 0 for key, value in latency.items()
    ):
        raise ValueError("Invalid attribution latency table.")
    if not isinstance(prices, Mapping) or not prices or any(
        key not in STEP_KINDS or type(value) is not int or value < 0 for key, value in prices.items()
    ):
        raise ValueError("Invalid attribution price table.")
    if "read" in prices and prices["read"] != 0:
        raise ValueError("Attribution reads must price zero.")
    return {"latency_ms": dict(latency), "price_table": dict(prices)}


def load_scenario(path: Path = SCENARIO_PATH) -> ScenarioDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0" or raw.get("scenario_id") != "support-triage":
        raise ValueError("Unsupported support-triage scenario document.")
    routes = raw.get("routes")
    if not isinstance(routes, list) or tuple(routes) != ROUTES:
        raise ValueError("Scenario routes must match the canonical M0 routes.")
    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Scenario cases must be an array.")
    attribution = parse_attribution(raw.get("attribution"))
    return ScenarioDefinition("1.0", "support-triage", ROUTES, tuple(_parse_case(item) for item in cases), attribution)


def find_scenario_case(scenario: ScenarioDefinition, case_id: str) -> ScenarioCase:
    for candidate in scenario.cases:
        if candidate.id == case_id:
            return candidate
    raise ValueError(f"Unknown scenario case: {case_id}")
