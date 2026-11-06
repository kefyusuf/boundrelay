"""M2-schema-valid result assembly with structural validation.

Mirrors the closed result schema (contracts/results/handoff-result
.schema.json) by hand: exact field sets, enums, status conditionals
(including the INVALID_ROUTE_DECISION null-selection branch), and
attribution totals equal to the sum of steps (stronger than the JSON
schema).
"""
import math
from copy import deepcopy

from .fixtures import FAILURE_CODES, RECEIVER_NAMES, ROUTES, SCENARIO_ID

RESULT_FIELDS = frozenset({
    "schema_version", "run_id", "scenario_id", "case_id", "router_mode",
    "status", "proposed_route", "selected_route", "receiver",
    "fallback_applied", "specialist_invoked", "failure_code", "trace_path",
    "attribution",
})
ROUTER_MODES = frozenset({"code", "model"})
STATUSES = frozenset({"SUCCEEDED", "FAILED"})
HANDOFF_FAILURE_CODES = frozenset({"HANDOFF_CONTEXT_INVALID",
                                   "HANDOFF_RECEIVER_UNAVAILABLE"})


def finite_json(value, seen=None, depth=0):
    """Mirror of the finite-JSON guard (no cycles, no NaN/Inf, bounds)."""
    if depth > 32:
        return False
    if value is None or type(value) in (str, bool):
        return True
    if type(value) is int:
        return -(2 ** 53 - 1) <= value <= 2 ** 53 - 1
    if type(value) is float:
        return (math.isfinite(value)
                and (not value.is_integer() or abs(value) <= 2 ** 53 - 1))
    if type(value) not in (dict, list, tuple):
        return False
    seen = set() if seen is None else seen
    marker = id(value)
    if marker in seen:
        return False
    seen.add(marker)
    try:
        if type(value) is dict:
            return all(type(key) is str and finite_json(item, seen, depth + 1)
                       for key, item in value.items())
        return all(finite_json(item, seen, depth + 1) for item in value)
    finally:
        seen.remove(marker)


def _is_int(value, minimum):
    return type(value) is int and value >= minimum


def _valid_attribution(attribution):
    if type(attribution) is not dict or set(attribution) != {"steps", "totals"}:
        return False
    steps = attribution["steps"]
    if type(steps) is not list or not steps:
        return False
    for step in steps:
        if (type(step) is not dict
                or set(step) != {"step_name", "latency_ms", "cost_cents",
                                 "attempts"}
                or type(step["step_name"]) is not str
                or not step["step_name"]
                or not _is_int(step["latency_ms"], 0)
                or not _is_int(step["cost_cents"], 0)
                or not _is_int(step["attempts"], 1)):
            return False
    totals = attribution["totals"]
    if type(totals) is not dict or set(totals) != {"latency_ms", "cost_cents",
                                                   "attempts"}:
        return False
    sums = {key: sum(step[key] for step in steps)
            for key in ("latency_ms", "cost_cents", "attempts")}
    return totals == sums


def validate_result(result):
    """Structural mirror of the closed M2 handoff result schema + totals."""
    if not finite_json(result) or type(result) is not dict:
        return False
    if set(result) != RESULT_FIELDS:
        return False
    if (result["schema_version"] != "1.0"
            or result["scenario_id"] != SCENARIO_ID
            or type(result["run_id"]) is not str or not result["run_id"]
            or type(result["case_id"]) is not str or not result["case_id"]
            or type(result["trace_path"]) is not str
            or not result["trace_path"]
            or result["router_mode"] not in ROUTER_MODES
            or type(result["fallback_applied"]) is not bool
            or type(result["specialist_invoked"]) is not bool
            or not _valid_attribution(result["attribution"])):
        return False
    if result["status"] == "SUCCEEDED":
        if (result["proposed_route"] not in ROUTES
                or result["selected_route"] not in ROUTES
                or result["receiver"] not in RECEIVER_NAMES
                or result["specialist_invoked"] is not True
                or result["failure_code"] is not None):
            return False
    elif result["status"] == "FAILED":
        if (result["specialist_invoked"] is not False
                or result["failure_code"] not in FAILURE_CODES):
            return False
    else:
        return False
    if result["failure_code"] in HANDOFF_FAILURE_CODES:
        return (result["proposed_route"] in ROUTES
                and result["selected_route"] in ROUTES
                and result["receiver"] in RECEIVER_NAMES)
    if result["failure_code"] == "INVALID_ROUTE_DECISION":
        return (result["proposed_route"] is None
                and result["selected_route"] is None
                and result["receiver"] is None
                and result["fallback_applied"] is False)
    return True


def assemble_result(*, run_id, trace_path, case_id, router_mode, status,
                    proposed_route, selected_route, receiver,
                    fallback_applied, specialist_invoked, failure_code,
                    attribution):
    """Assemble the published result; validate before publication."""
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "scenario_id": SCENARIO_ID,
        "case_id": case_id,
        "router_mode": router_mode,
        "status": status,
        "proposed_route": proposed_route,
        "selected_route": selected_route,
        "receiver": receiver,
        "fallback_applied": fallback_applied,
        "specialist_invoked": specialist_invoked,
        "failure_code": failure_code,
        "trace_path": trace_path,
        "attribution": deepcopy(attribution),
    }
    if not validate_result(result):
        raise ValueError("Invalid run result")
    return result
