"""M1-schema-valid result assembly with structural validation.

Mirrors the closed result schema (contracts/results/tool-loop-result
.schema.json) by hand: exact field sets, enums, status conditionals, and
attribution totals equal to the sum of steps (stronger than the JSON
schema).
"""
import math
from copy import deepcopy

from .fixtures import FAILURE_CODES, SCENARIO_ID

RESULT_FIELDS = frozenset({
    "schema_version", "run_id", "scenario_id", "case_id", "mode", "status",
    "answer", "failure_code", "model_steps", "tokens_used",
    "tool_invocations", "trace_path", "attribution",
})
MODES = frozenset({"direct", "agent"})
STATUSES = frozenset({"SUCCEEDED", "FAILED"})


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
    """Structural mirror of the closed M1 result schema + totals = sum."""
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
            or result["mode"] not in MODES
            or not _is_int(result["model_steps"], 0)
            or not _is_int(result["tokens_used"], 0)
            or not _is_int(result["tool_invocations"], 0)
            or not _valid_attribution(result["attribution"])):
        return False
    if result["status"] == "SUCCEEDED":
        return (type(result["answer"]) is str and bool(result["answer"])
                and result["failure_code"] is None)
    if result["status"] == "FAILED":
        return (result["answer"] is None
                and result["failure_code"] in FAILURE_CODES)
    return False


def assemble_result(*, run_id, trace_path, case_id, mode, status, answer,
                    failure_code, model_steps, tokens_used, tool_invocations,
                    attribution):
    """Assemble the published result; validate before publication."""
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "scenario_id": SCENARIO_ID,
        "case_id": case_id,
        "mode": mode,
        "status": status,
        "answer": answer,
        "failure_code": failure_code,
        "model_steps": model_steps,
        "tokens_used": tokens_used,
        "tool_invocations": tool_invocations,
        "trace_path": trace_path,
        "attribution": deepcopy(attribution),
    }
    if not validate_result(result):
        raise ValueError("Invalid run result")
    return result
