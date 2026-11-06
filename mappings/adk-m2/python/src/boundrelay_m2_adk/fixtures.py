"""Strict fixture loading for the P5b Google ADK mapping.

Reads the canonical Go fixture projections
(fixtures/goprojections/support-handoff/{scenario,fake-model,failures,
attribution}.json), the M2 goldens' result projections
(fixtures/goldens/support-handoff/), and the closed contract schemas
(contracts/routing/, contracts/handoffs/). Checked-in artifacts only:
no YAML, no network, no mutation of the sources.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
PROJECTION_DIR = ROOT / "fixtures/goprojections/support-handoff"
GOLDEN_DIR = ROOT / "fixtures/goldens/support-handoff"
ROUTE_SCHEMA_PATH = ROOT / "contracts/routing/route-decision.schema.json"
HANDOFF_SCHEMA_PATH = ROOT / "contracts/handoffs/support-handoff.schema.json"
SCENARIO_ID = "support-handoff"
ROUTES = ("billing", "technical", "general")
RECEIVER_NAMES = ("billing-specialist", "technical-specialist",
                  "general-specialist")
RECEIVER_BY_ROUTE = {"billing": "billing-specialist",
                     "technical": "technical-specialist",
                     "general": "general-specialist"}
RECEIVER_INPUT_FIELDS = ("ticket_id", "request_text")
FAILURE_CODES = ("INVALID_ROUTE_DECISION", "HANDOFF_CONTEXT_INVALID",
                 "HANDOFF_RECEIVER_UNAVAILABLE")
STEP_KINDS = ("read", "model_decision", "tool_call", "effect", "handoff",
              "route", "synthesis")
PARITY_CASE_KEYS = (
    "code-billing-handoff",
    "model-technical-handoff",
    "model-low-confidence-fallback",
    "handoff-context-loss",
    "handoff-receiver-unavailable",
)
CONFIDENCE_THRESHOLD = 0.80
TICKET_PATTERN = re.compile(r"TCK-[0-9]{4}")


def _fields(raw, keys):
    if type(raw) is not dict or set(raw) != set(keys):
        raise ValueError("Invalid fixture fields")
    return raw


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid fixture document: {path.name}") from error


def _route(value):
    if type(value) is not str or value not in ROUTES:
        raise ValueError("Invalid route")
    return value


def _receiver(value):
    if type(value) is not str or value not in RECEIVER_NAMES:
        raise ValueError("Invalid receiver")
    return value


def _confidence(value):
    if isinstance(value, bool) or type(value) not in (int, float):
        raise ValueError("Invalid confidence")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("Invalid confidence")
    return number


def parse_attribution(raw):
    _fields(raw, ["latency_ms", "price_table"])
    latency = raw["latency_ms"]
    prices = raw["price_table"]
    if (type(latency) is not dict or not latency or any(
            type(key) is not str or not key or type(value) is not int
            or value < 0 for key, value in latency.items())):
        raise ValueError("Invalid attribution latency table")
    if (type(prices) is not dict or not prices or any(
            key not in STEP_KINDS or type(value) is not int or value < 0
            for key, value in prices.items())):
        raise ValueError("Invalid attribution price table")
    return {"latency_ms": dict(latency), "price_table": dict(prices)}


CASE_FIELDS = (
    "id", "ticket_id", "request", "router_mode", "expected_status",
    "expected_proposed_route", "expected_confidence", "expected_selected_route",
    "expected_receiver", "expected_policy_outcome", "expected_fallback_applied",
    "expected_specialist_invoked", "expected_failure_code", "failure_ref",
)
CASE_SUCCESS_FIELDS = CASE_FIELDS[:12]


def parse_case(raw, failures):
    if type(raw) is not dict:
        raise ValueError("Scenario case must be an object")
    keys = set(raw)
    if keys == set(CASE_SUCCESS_FIELDS):
        pass
    elif keys == set(CASE_FIELDS):
        pass
    else:
        raise ValueError("Invalid case fields")
    case_id = raw["id"]
    if (type(case_id) is not str or not case_id
            or raw["router_mode"] not in ("code", "model")
            or raw["expected_status"] not in ("SUCCEEDED", "FAILED")
            or type(raw["request"]) is not str or not raw["request"]
            or TICKET_PATTERN.fullmatch(raw["ticket_id"]) is None
            or type(raw["expected_fallback_applied"]) is not bool
            or type(raw["expected_specialist_invoked"]) is not bool):
        raise ValueError(f"Invalid case specification: {case_id}")
    _route(raw["expected_proposed_route"])
    _confidence(raw["expected_confidence"])
    _route(raw["expected_selected_route"])
    _receiver(raw["expected_receiver"])
    if raw["expected_policy_outcome"] not in ("selected", "fallback"):
        raise ValueError(f"Invalid policy outcome: {case_id}")
    if raw["expected_status"] == "SUCCEEDED":
        return dict(raw)
    if raw["expected_failure_code"] not in FAILURE_CODES:
        raise ValueError(f"{case_id} has an unsupported failure code")
    failure_ref = raw["failure_ref"]
    if type(failure_ref) is not str or failure_ref not in failures:
        raise ValueError(f"Unknown failure_ref: {failure_ref}")
    return dict(raw)


def parse_scenario(raw):
    _fields(raw, ["schema_version", "scenario_id", "confidence_threshold",
                  "route_receivers", "attribution", "cases"])
    if raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID:
        raise ValueError("Invalid scenario projection")
    if (isinstance(raw["confidence_threshold"], bool)
            or type(raw["confidence_threshold"]) not in (int, float)
            or float(raw["confidence_threshold"]) != CONFIDENCE_THRESHOLD):
        raise ValueError("confidence_threshold must be 0.80")
    route_receivers = raw["route_receivers"]
    if (type(route_receivers) is not dict
            or {route: _receiver(receiver)
                for route, receiver in route_receivers.items()}
            != RECEIVER_BY_ROUTE):
        raise ValueError("route_receivers must be the canonical mapping")
    failures = parse_failures(_load_json(
        PROJECTION_DIR / "failures.json"))["failures"]
    if (type(raw["cases"]) is not list
            or [case["id"] for case in raw["cases"]] != list(PARITY_CASE_KEYS)):
        raise ValueError("Scenario must contain exactly the five canonical M2 cases")
    cases = [parse_case(case, failures) for case in raw["cases"]]
    return {"schema_version": "1.0", "scenario_id": SCENARIO_ID,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "route_receivers": dict(RECEIVER_BY_ROUTE),
            "cases": cases, "attribution": parse_attribution(raw["attribution"])}


def parse_decisions(raw):
    _fields(raw, ["schema_version", "scenario_id", "decisions"])
    if raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID:
        raise ValueError("Invalid fake-model projection")
    decisions = raw["decisions"]
    model_cases = ("model-technical-handoff", "model-low-confidence-fallback",
                   "handoff-context-loss")
    if type(decisions) is not dict or tuple(sorted(decisions)) != tuple(
            sorted(model_cases)):
        raise ValueError("Decisions must cover exactly the model-mode cases")
    parsed = {}
    for case_id, decision in decisions.items():
        _fields(decision, ["route", "confidence"])
        parsed[case_id] = {"route": _route(decision["route"]),
                           "confidence": _confidence(decision["confidence"])}
    return parsed


def parse_failures(raw):
    _fields(raw, ["schema_version", "scenario_id", "failures"])
    if raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID:
        raise ValueError("Invalid failures projection")
    failures = raw["failures"]
    if type(failures) is not dict or set(failures) != {
            "handoff-context-loss", "handoff-receiver-unavailable"}:
        raise ValueError("Failures must cover exactly the handoff cases")
    parsed = {}
    for case_id, operator in failures.items():
        if case_id.startswith(("code-", "model-")):
            raise ValueError(f"{case_id} success case cannot define failure operators")
        if type(operator) is not dict or len(operator) != 1:
            raise ValueError(f"{case_id} must define exactly one failure operator")
        if "omit_receiver_input_fields" in operator:
            fields = operator["omit_receiver_input_fields"]
            if (type(fields) is not list or not fields or any(
                    field not in RECEIVER_INPUT_FIELDS for field in fields)):
                raise ValueError(f"{case_id} omit_receiver_input_fields is invalid")
            parsed[case_id] = {"omit_receiver_input_fields": tuple(fields)}
        elif "unavailable_receivers" in operator:
            receivers = operator["unavailable_receivers"]
            if (type(receivers) is not list or not receivers or any(
                    _receiver(receiver) is None for receiver in receivers)):
                raise ValueError(f"{case_id} unavailable_receivers is invalid")
            parsed[case_id] = {"unavailable_receivers": tuple(receivers)}
        else:
            raise ValueError(f"{case_id} has an unsupported failure operator")
    return {"schema_version": "1.0", "scenario_id": SCENARIO_ID,
            "failures": parsed}


def load_scenario_projection():
    return parse_scenario(_load_json(PROJECTION_DIR / "scenario.json"))


def load_fake_model_projection():
    return parse_decisions(_load_json(PROJECTION_DIR / "fake-model.json"))


def load_failures_projection():
    return parse_failures(_load_json(
        PROJECTION_DIR / "failures.json"))["failures"]


def load_attribution_projection():
    return parse_attribution(_load_json(PROJECTION_DIR / "attribution.json"))


def load_golden(case_key):
    """The M2 golden's result_projection: the parity target for one case."""
    if case_key not in PARITY_CASE_KEYS:
        raise ValueError(f"Unknown parity case: {case_key}")
    golden = _load_json(GOLDEN_DIR / f"{case_key}.json")
    if (type(golden) is not dict or golden.get("case_key") != case_key
            or type(golden.get("result_projection")) is not dict
            or "attribution" not in golden["result_projection"]):
        raise ValueError(f"Invalid golden projection: {case_key}")
    return golden["result_projection"]


def load_route_decision_schema():
    schema = _load_json(ROUTE_SCHEMA_PATH)
    if type(schema) is not dict or schema.get("type") != "object":
        raise ValueError("Invalid route-decision schema")
    return schema


def load_handoff_schema():
    schema = _load_json(HANDOFF_SCHEMA_PATH)
    if type(schema) is not dict or schema.get("type") != "object":
        raise ValueError("Invalid handoff schema")
    return schema


@dataclass
class RunCase:
    case_id: str
    ticket_id: str
    request: str
    router_mode: str
    decision: object
    failure: object
    latency_ms: dict
    price_table: dict


def load_case(case_id):
    """Assemble every run input for one parity case (strict, offline)."""
    scenario = load_scenario_projection()
    spec = next((case for case in scenario["cases"]
                 if case["id"] == case_id), None)
    if spec is None:
        raise ValueError(f"Unknown case: {case_id}")
    tables = parse_attribution(scenario["attribution"])
    failure = (load_failures_projection()[spec["failure_ref"]]
               if spec.get("failure_ref") else None)
    decision = (load_fake_model_projection()[case_id]
                if spec["router_mode"] == "model" else None)
    return RunCase(
        case_id=spec["id"], ticket_id=spec["ticket_id"],
        request=spec["request"], router_mode=spec["router_mode"],
        decision=decision, failure=failure,
        latency_ms=tables["latency_ms"], price_table=tables["price_table"])


if __name__ == "__main__":  # pragma: no cover - manual smoke only
    print(load_case("model-low-confidence-fallback"))
