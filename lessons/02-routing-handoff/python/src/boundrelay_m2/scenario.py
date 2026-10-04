from pathlib import Path
import re
from typing import Mapping, cast

import yaml

from .paths import FAILURES_PATH, SCENARIO_PATH
from .types import (
    FAILURE_CODES,
    RECEIVER_NAMES,
    ROUTES,
    FailureCode,
    FailureFixtures,
    OmitReceiverInputFailure,
    PolicyOutcome,
    ReceiverInputField,
    ReceiverName,
    Route,
    RouterMode,
    RunStatus,
    ScenarioCase,
    ScenarioDefinition,
    UnavailableReceiversFailure,
)


def _is_mapping(value: object) -> bool:
    return isinstance(value, Mapping)


def _require_string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string.")
    return value


def _require_number(record: Mapping[str, object], key: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a finite number.")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{key} must be a finite number.")
    return number


def _require_boolean(record: Mapping[str, object], key: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean.")
    return value


def _enum_value(value: object, allowed: tuple[str, ...], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} is unsupported.")
    return value


def _exact_keys(record: Mapping[str, object], allowed: tuple[str, ...], label: str) -> None:
    extras = [key for key in record if key not in allowed]
    if extras:
        raise ValueError(f"{label} has unsupported field: {extras[0]}")


def load_failure_fixtures(path: Path | Mapping[str, object] = FAILURES_PATH) -> FailureFixtures:
    raw = path if isinstance(path, Mapping) else yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, Mapping)
        or raw.get("schema_version") != "1.0"
        or raw.get("scenario_id") != "support-handoff"
        or not isinstance(raw.get("failures"), Mapping)
    ):
        raise ValueError("Unsupported support-handoff failure fixture.")

    result: FailureFixtures = {}
    failures = cast(Mapping[object, object], raw["failures"])
    for case_id, value in failures.items():
        if not isinstance(case_id, str) or not isinstance(value, Mapping):
            raise ValueError(f"{case_id} failure fixture must be an object.")
        keys = tuple(value.keys())
        if len(keys) != 1 or keys[0] not in ("omit_receiver_input_fields", "unavailable_receivers"):
            raise ValueError(f"{case_id} has unsupported failure operator.")
        if case_id.startswith(("code-", "model-")):
            raise ValueError(f"{case_id} success case cannot define failure operators.")
        if keys[0] == "omit_receiver_input_fields":
            fields = value.get("omit_receiver_input_fields")
            if (
                not isinstance(fields, list)
                or not fields
                or any(field not in ("ticket_id", "request_text") for field in fields)
            ):
                raise ValueError(f"{case_id} omit_receiver_input_fields is invalid.")
            result[case_id] = OmitReceiverInputFailure(
                tuple(cast(ReceiverInputField, field) for field in fields)
            )
        else:
            receivers = value.get("unavailable_receivers")
            if (
                not isinstance(receivers, list)
                or not receivers
                or any(not isinstance(receiver, str) or receiver not in RECEIVER_NAMES for receiver in receivers)
            ):
                raise ValueError(f"{case_id} unavailable_receivers is invalid.")
            result[case_id] = UnavailableReceiversFailure(
                tuple(cast(ReceiverName, receiver) for receiver in receivers)
            )
    return result


def _parse_case(raw: object, failures: FailureFixtures) -> ScenarioCase:
    if not isinstance(raw, Mapping):
        raise ValueError("Scenario case must be an object.")
    case_id = _require_string(raw, "id")
    _exact_keys(
        raw,
        (
            "id",
            "ticket_id",
            "request",
            "router_mode",
            "expected_status",
            "expected_proposed_route",
            "expected_confidence",
            "expected_selected_route",
            "expected_receiver",
            "expected_policy_outcome",
            "expected_fallback_applied",
            "expected_specialist_invoked",
            "expected_failure_code",
            "failure_ref",
        ),
        case_id,
    )
    expected_status = cast(RunStatus, _enum_value(raw.get("expected_status"), ("SUCCEEDED", "FAILED"), "expected_status"))
    item = ScenarioCase(
        id=case_id,
        ticket_id=_require_string(raw, "ticket_id"),
        request=_require_string(raw, "request"),
        router_mode=cast(RouterMode, _enum_value(raw.get("router_mode"), ("code", "model"), "router_mode")),
        expected_status=expected_status,
        expected_proposed_route=cast(Route, _enum_value(raw.get("expected_proposed_route"), ROUTES, "expected_proposed_route")),
        expected_confidence=_require_number(raw, "expected_confidence"),
        expected_selected_route=cast(Route, _enum_value(raw.get("expected_selected_route"), ROUTES, "expected_selected_route")),
        expected_receiver=cast(ReceiverName, _enum_value(raw.get("expected_receiver"), RECEIVER_NAMES, "expected_receiver")),
        expected_policy_outcome=cast(PolicyOutcome, _enum_value(raw.get("expected_policy_outcome"), ("selected", "fallback"), "expected_policy_outcome")),
        expected_fallback_applied=_require_boolean(raw, "expected_fallback_applied"),
        expected_specialist_invoked=_require_boolean(raw, "expected_specialist_invoked"),
    )
    if re.fullmatch(r"TCK-[0-9]{4}", item.ticket_id) is None:
        raise ValueError(f"{case_id} ticket_id is invalid.")
    if not 0 <= item.expected_confidence <= 1:
        raise ValueError(f"{case_id} expected_confidence must be between 0 and 1.")
    if expected_status == "SUCCEEDED":
        if raw.get("expected_failure_code") is not None or raw.get("failure_ref") is not None:
            raise ValueError(f"{case_id} success case cannot define failure fields.")
        return item

    failure_code = cast(FailureCode, _enum_value(raw.get("expected_failure_code"), FAILURE_CODES, "expected_failure_code"))
    failure_ref = _require_string(raw, "failure_ref")
    if failure_ref not in failures:
        raise ValueError(f"Unknown failure_ref: {failure_ref}")
    return ScenarioCase(
        **{**item.__dict__, "expected_failure_code": failure_code, "failure_ref": failure_ref}
    )


def load_scenario(path: Path | Mapping[str, object] = SCENARIO_PATH, failure_path: Path = FAILURES_PATH) -> ScenarioDefinition:
    failures = load_failure_fixtures(failure_path)
    raw = path if isinstance(path, Mapping) else yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, Mapping)
        or raw.get("schema_version") != "1.0"
        or raw.get("scenario_id") != "support-handoff"
    ):
        raise ValueError("Unsupported support-handoff scenario document.")
    threshold = raw.get("confidence_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("confidence_threshold must be a finite number.")
    if float(threshold) != 0.80:
        raise ValueError("confidence_threshold must be 0.80.")
    route_receivers = raw.get("route_receivers")
    if not isinstance(route_receivers, Mapping):
        raise ValueError("route_receivers must be an object.")
    expected_mapping: dict[Route, ReceiverName] = {
        "billing": "billing-specialist",
        "technical": "technical-specialist",
        "general": "general-specialist",
    }
    _exact_keys(route_receivers, ROUTES, "route_receivers")
    for route in ROUTES:
        if route_receivers.get(route) != expected_mapping[route]:
            raise ValueError(f"route_receivers.{route} must be {expected_mapping[route]}.")
    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Scenario cases must be an array.")
    parsed = tuple(_parse_case(case, failures) for case in cases)
    ids = {case.id for case in parsed}
    if len(ids) != len(parsed):
        raise ValueError("Scenario case ids must be unique.")
    expected_ids = {"code-billing-handoff", "model-technical-handoff", "model-low-confidence-fallback", "handoff-context-loss", "handoff-receiver-unavailable"}
    if ids != expected_ids:
        raise ValueError("Scenario must contain exactly the five canonical M2 cases.")
    for case in parsed:
        expected_ref = case.id if case.id.startswith("handoff-") else None
        if case.failure_ref != expected_ref:
            raise ValueError(f"{case.id} has an invalid M2 failure reference.")
    return ScenarioDefinition("1.0", "support-handoff", 0.80, expected_mapping, parsed)


def find_scenario_case(scenario: ScenarioDefinition, case_id: str) -> ScenarioCase:
    for candidate in scenario.cases:
        if candidate.id == case_id:
            return candidate
    raise ValueError(f"Unknown scenario case: {case_id}")
