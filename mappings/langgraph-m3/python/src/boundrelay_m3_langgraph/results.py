"""M3-schema-valid result assembly with structural validation.

Mirrors the closed result schema (contracts/results/order-brief-result
.schema.json) by hand: exact field sets, enums, ORD pattern, canonical
worker_outcomes ordering, and the status conditionals. Attribution
totals must equal the sum of steps (stronger than the JSON schema).
"""
import math
from copy import deepcopy
from dataclasses import dataclass

from .fixtures import ORD_PATTERN, WORKER_IDS

RESULT_FIELDS = frozenset({
    "schema_version", "run_id", "scenario_id", "case_id", "execution_mode",
    "concurrency_limit", "peak_concurrency", "order_id", "status",
    "worker_outcomes", "synthesis_invoked", "brief", "failure_code",
    "trace_path", "attribution",
})
OUTCOME_FIELDS = frozenset({"worker_id", "status", "output", "failure_code"})
SECTION_FIELDS = frozenset({"worker_id", "output"})
BRIEF_FIELDS = frozenset({"order_id", "sections", "missing_workers",
                          "complete"})
WORKER_FAILURE_CODES = frozenset({"WORKER_EXECUTION_FAILED",
                                  "INVALID_WORKER_OUTPUT"})
WORKER_OUTPUT_FIELDS = {
    "order-details": ("order_status",
                      frozenset({"PROCESSING", "SHIPPED", "CANCELLED"})),
    "payment-status": ("payment_status", frozenset({"PAID", "UNPAID"})),
    "delivery-status": ("delivery_status",
                        frozenset({"PENDING", "IN_TRANSIT", "DELIVERED",
                                   "DELAYED"})),
}
@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    value: object = None


def finite_json(value, seen=None, depth=0):
    """Mirror of the M3 finite-JSON guard (no cycles, no NaN/Inf, bounds)."""
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


def _is_ord(value):
    return type(value) is str and ORD_PATTERN.fullmatch(value) is not None
def validate_worker_output(worker_id, raw, order_id):
    """Raw return -> valid output? Mirrors the worker-result schema."""
    if not finite_json(raw) or type(raw) is not dict:
        return ValidationResult(False)
    if raw.get("order_id") != order_id:
        return ValidationResult(False)
    if worker_id not in WORKER_OUTPUT_FIELDS:
        return ValidationResult(False)
    field_name, allowed = WORKER_OUTPUT_FIELDS[worker_id]
    if set(raw) != {"order_id", field_name} or raw[field_name] not in allowed:
        return ValidationResult(False)
    return ValidationResult(True, deepcopy(raw))


def _valid_success_outcome(outcome, order_id):
    worker_id = outcome["worker_id"]
    if worker_id not in WORKER_IDS:
        return False
    output = outcome["output"]
    if type(output) is not dict:
        return False
    field_name, allowed = WORKER_OUTPUT_FIELDS[worker_id]
    if (set(output) != {"order_id", field_name}
            or output.get("order_id") != order_id
            or output.get(field_name) not in allowed):
        return False
    return outcome["failure_code"] is None


def validate_worker_outcome(outcome, order_id):
    """One canonical outcome dict (SUCCEEDED or FAILED shape)."""
    if type(outcome) is not dict or finite_json(outcome) is False:
        return False
    if set(outcome) != OUTCOME_FIELDS or outcome["worker_id"] not in WORKER_IDS:
        return False
    if outcome["status"] == "SUCCEEDED":
        return _valid_success_outcome(outcome, order_id)
    if outcome["status"] == "FAILED":
        return (outcome["output"] is None
                and outcome["failure_code"] in WORKER_FAILURE_CODES)
    return False
def canonicalize_outcomes(raw, order_id):
    """Fan-in gate: exactly 3 unique valid outcomes -> canonical order."""
    if type(raw) not in (list, tuple) or len(raw) != 3:
        raise ValueError("Incomplete or invalid fan in")
    if not all(validate_worker_outcome(outcome, order_id) for outcome in raw):
        raise ValueError("Incomplete or invalid fan in")
    if len({outcome["worker_id"] for outcome in raw}) != 3:
        raise ValueError("Duplicate worker identity")
    return tuple(deepcopy(next(outcome for outcome in raw
                               if outcome["worker_id"] == worker_id))
                 for worker_id in WORKER_IDS)


def synthesize_brief(order_id, outcomes):
    """One deterministic synthesizer over canonical outcomes."""
    canonical = canonicalize_outcomes(outcomes, order_id)
    sections = [{"worker_id": outcome["worker_id"],
                 "output": outcome["output"]}
                for outcome in canonical if outcome["status"] == "SUCCEEDED"]
    if not sections:
        raise ValueError("Cannot synthesize without successful evidence")
    missing = [outcome["worker_id"] for outcome in canonical
               if outcome["status"] == "FAILED"]
    return {"order_id": order_id, "sections": sections,
            "missing_workers": missing, "complete": not missing}
def _is_int(value, minimum):
    return type(value) is int and value >= minimum


def _valid_brief(brief, order_id, expected_complete):
    if type(brief) is not dict or set(brief) != BRIEF_FIELDS:
        return False
    if brief["order_id"] != order_id or type(brief["complete"]) is not bool:
        return False
    if brief["complete"] != expected_complete:
        return False
    sections = brief["sections"]
    if type(sections) is not list or not 1 <= len(sections) <= 3:
        return False
    for section in sections:
        if (type(section) is not dict
                or set(section) != SECTION_FIELDS
                or section["worker_id"] not in WORKER_IDS
                or not _valid_success_outcome(
                    {"worker_id": section["worker_id"],
                     "output": section["output"],
                     "failure_code": None}, order_id)):
            return False
    missing = brief["missing_workers"]
    if (type(missing) is not list or len(missing) > 2
            or len(set(missing)) != len(missing)
            or any(worker_id not in WORKER_IDS for worker_id in missing)):
        return False
    succeeded = {section["worker_id"] for section in sections}
    failed = {worker_id for worker_id in WORKER_IDS if worker_id not in succeeded}
    return set(missing) == failed
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
    """Structural mirror of the closed M3 result schema + totals = sum."""
    if not finite_json(result) or type(result) is not dict:
        return False
    if set(result) != RESULT_FIELDS:
        return False
    if (result["schema_version"] != "1.0"
            or result["scenario_id"] != "order-brief"
            or not _is_ord(result["order_id"])
            or type(result["run_id"]) is not str or not result["run_id"]
            or type(result["case_id"]) is not str or not result["case_id"]
            or type(result["trace_path"]) is not str
            or not result["trace_path"]):
        return False
    if result["execution_mode"] == "sequential":
        if result["concurrency_limit"] != 1 or result["peak_concurrency"] != 1:
            return False
    elif result["execution_mode"] == "parallel":
        if result["concurrency_limit"] != 2:
            return False
    else:
        return False
    if not (_is_int(result["peak_concurrency"], 1)
            and result["peak_concurrency"] <= 2):
        return False
    return _valid_status_shape(result)


def _valid_status_shape(result):
    outcomes = result["worker_outcomes"]
    if type(outcomes) is not list or len(outcomes) != 3:
        return False
    order_id = result["order_id"]
    if not all(validate_worker_outcome(outcome, order_id)
               for outcome in outcomes):
        return False
    if [outcome["worker_id"] for outcome in outcomes] != list(WORKER_IDS):
        return False
    successes = sum(outcome["status"] == "SUCCEEDED" for outcome in outcomes)
    if result["status"] == "SUCCEEDED" and successes == 3:
        return (result["synthesis_invoked"] is True
                and result["failure_code"] is None
                and _valid_brief(result["brief"], order_id, True))
    if result["status"] == "PARTIAL" and 1 <= successes <= 2:
        return (result["synthesis_invoked"] is True
                and result["failure_code"] is None
                and _valid_brief(result["brief"], order_id, False))
    if result["status"] == "FAILED" and successes == 0:
        return (result["synthesis_invoked"] is False
                and result["failure_code"] == "ALL_WORKERS_FAILED"
                and result["brief"] is None)
    return False


def assemble_result(*, run_id, trace_path, case, peak_concurrency, outcomes,
                    attribution):
    """Assemble the published result; validate before publication."""
    canonical = canonicalize_outcomes(outcomes, case.order_id)
    successes = sum(outcome["status"] == "SUCCEEDED"
                    for outcome in canonical)
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "scenario_id": "order-brief",
        "case_id": case.case_id,
        "execution_mode": case.execution_mode,
        "concurrency_limit": case.limit,
        "peak_concurrency": peak_concurrency,
        "order_id": case.order_id,
        "status": ("SUCCEEDED" if successes == 3
                   else "PARTIAL" if successes else "FAILED"),
        "worker_outcomes": list(canonical),
        "synthesis_invoked": bool(successes),
        "brief": synthesize_brief(case.order_id, canonical) if successes
        else None,
        "failure_code": None if successes else "ALL_WORKERS_FAILED",
        "trace_path": trace_path,
        "attribution": attribution,
    }
    if not validate_result(result):
        raise ValueError("Invalid run result")
    return result
