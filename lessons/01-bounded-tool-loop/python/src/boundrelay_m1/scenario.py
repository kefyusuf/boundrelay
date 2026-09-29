from copy import deepcopy
from pathlib import Path
from typing import Mapping, cast

import yaml

from .paths import SCENARIO_PATH
from .types import (
    FAILURE_CODES,
    TOOL_NAMES,
    DirectCall,
    FailureCode,
    RunMode,
    ScenarioCase,
    ScenarioDefinition,
    ScenarioFailureCase,
    ScenarioSuccessCase,
    ToolName,
)


def _require_string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string.")
    return value


def _require_non_negative_integer(record: Mapping[str, object], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer.")
    return value


def _parse_mode(value: object) -> RunMode:
    if value not in ("direct", "agent"):
        raise ValueError("mode must be direct or agent.")
    return cast(RunMode, value)


def _parse_direct_call(value: object) -> DirectCall:
    if not isinstance(value, Mapping):
        raise ValueError("direct_call must be an object.")
    call_id = _require_string(value, "call_id")
    tool = value.get("tool")
    if not isinstance(tool, str) or tool not in TOOL_NAMES:
        raise ValueError("direct_call.tool must name an M1 tool.")
    arguments = value.get("arguments")
    if not isinstance(arguments, Mapping):
        raise ValueError("direct_call.arguments must be an object.")
    return DirectCall(call_id, cast(ToolName, tool), deepcopy(dict(arguments)))


def _parse_case(raw: object) -> ScenarioCase:
    if not isinstance(raw, Mapping):
        raise ValueError("Scenario case must be an object.")

    case_id = _require_string(raw, "id")
    mode = _parse_mode(raw.get("mode"))
    common = {
        "id": case_id,
        "mode": mode,
        "request": _require_string(raw, "request"),
        "max_steps": _require_non_negative_integer(raw, "max_steps"),
        "max_tokens": _require_non_negative_integer(raw, "max_tokens"),
        "expected_model_steps": _require_non_negative_integer(raw, "expected_model_steps"),
        "expected_tokens_used": _require_non_negative_integer(raw, "expected_tokens_used"),
        "expected_tool_invocations": _require_non_negative_integer(raw, "expected_tool_invocations"),
    }

    if raw.get("expected_status") == "SUCCEEDED":
        answer = raw.get("expected_answer")
        if not isinstance(answer, str) or not answer:
            raise ValueError(f"{case_id} expected_answer must be a non-empty string.")
        if raw.get("expected_failure_code") is not None:
            raise ValueError(f"{case_id} cannot define expected_failure_code on success.")
        if mode == "direct":
            direct_call = _parse_direct_call(raw.get("direct_call"))
        else:
            if raw.get("direct_call") is not None:
                raise ValueError(f"{case_id} agent mode cannot define direct_call.")
            direct_call = None
        return ScenarioSuccessCase(
            **common,
            expected_status="SUCCEEDED",
            expected_answer=answer,
            direct_call=direct_call,
        )

    if raw.get("expected_status") == "FAILED":
        if mode != "agent":
            raise ValueError(f"{case_id} failed canonical cases must use agent mode.")
        failure = raw.get("expected_failure_code")
        if not isinstance(failure, str) or failure not in FAILURE_CODES:
            raise ValueError(f"{case_id} expected_failure_code is unsupported.")
        if raw.get("expected_answer") is not None or raw.get("direct_call") is not None:
            raise ValueError(f"{case_id} failed case cannot define success-only fields.")
        failure_common = dict(common)
        failure_common["mode"] = "agent"
        return ScenarioFailureCase(
            **failure_common,
            expected_status="FAILED",
            expected_failure_code=cast(FailureCode, failure),
        )

    raise ValueError(f"{case_id} expected_status must be SUCCEEDED or FAILED.")


def load_scenario(path: Path = SCENARIO_PATH) -> ScenarioDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, Mapping)
        or raw.get("schema_version") != "1.0"
        or raw.get("scenario_id") != "order-investigation"
    ):
        raise ValueError("Unsupported order-investigation scenario document.")
    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Scenario cases must be an array.")
    parsed = tuple(_parse_case(item) for item in cases)
    ids = {item.id for item in parsed}
    if len(ids) != len(parsed):
        raise ValueError("Scenario case ids must be unique.")
    return ScenarioDefinition("1.0", "order-investigation", parsed)


def find_scenario_case(scenario: ScenarioDefinition, case_id: str) -> ScenarioCase:
    for candidate in scenario.cases:
        if candidate.id == case_id:
            return candidate
    raise ValueError(f"Unknown scenario case: {case_id}")
