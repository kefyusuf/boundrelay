"""Strict fixture loading for the P5 OpenAI Agents SDK mapping.

Reads the canonical Go fixture projections
(fixtures/goprojections/order-investigation/{scenario,fake-model,fake-tools,
attribution}.json), the M1 goldens' result projections
(fixtures/goldens/order-investigation/), and the closed tool-argument
schemas (contracts/tools/). Checked-in artifacts only: no YAML, no
network, no mutation of the sources.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
PROJECTION_DIR = ROOT / "fixtures/goprojections/order-investigation"
GOLDEN_DIR = ROOT / "fixtures/goldens/order-investigation"
ORDER_ARGUMENTS_SCHEMA_PATH = ROOT / "contracts/tools/lookup-order-arguments.schema.json"
SHIPMENT_ARGUMENTS_SCHEMA_PATH = ROOT / "contracts/tools/lookup-shipment-arguments.schema.json"
SCENARIO_ID = "order-investigation"
TOOL_NAMES = ("lookup_order", "lookup_shipment")
ORD_PATTERN = re.compile(r"ORD-[0-9]{4}")
SHIPMENT_PATTERN = re.compile(r"SHP-[0-9]{4}")
STEP_KINDS = ("read", "model_decision", "tool_call", "effect", "handoff",
              "route", "synthesis")
FAILURE_CODES = (
    "UNKNOWN_TOOL", "INVALID_TOOL_ARGUMENTS", "TOOL_TIMEOUT",
    "TOOL_EXECUTION_FAILED", "STEP_BUDGET_EXCEEDED", "TOKEN_BUDGET_EXCEEDED",
    "INVALID_MODEL_DECISION",
)
PARITY_CASE_KEYS = (
    "direct-order-status",
    "agent-delayed-shipment",
    "agent-unknown-tool",
    "agent-invalid-arguments",
    "agent-tool-timeout",
    "agent-tool-failure",
    "agent-step-budget",
    "agent-token-budget",
)
TOOL_BEHAVIORS = ("timeout", "failure")


def _fields(raw, keys):
    if type(raw) is not dict or set(raw) != set(keys):
        raise ValueError("Invalid fixture fields")
    return raw


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid fixture document: {path.name}") from error


def _non_negative_int(value):
    return type(value) is int and value >= 0


def _valid_latency(raw):
    return (type(raw) is dict and bool(raw) and all(
        type(key) is str and key and type(value) is int and value >= 0
        for key, value in raw.items()))


def _valid_price_table(raw):
    return (type(raw) is dict and bool(raw) and all(
        key in STEP_KINDS and type(value) is int and value >= 0
        for key, value in raw.items()))


def parse_attribution(raw):
    _fields(raw, ["latency_ms", "price_table"])
    if not _valid_latency(raw["latency_ms"]):
        raise ValueError("Invalid attribution latency table")
    if not _valid_price_table(raw["price_table"]):
        raise ValueError("Invalid attribution price table")
    return {"latency_ms": dict(raw["latency_ms"]),
            "price_table": dict(raw["price_table"])}


def _parse_direct_call(raw):
    if type(raw) is not dict:
        raise ValueError("direct_call must be an object")
    _fields(raw, ["call_id", "tool", "arguments"])
    if (type(raw["call_id"]) is not str or not raw["call_id"]
            or raw["tool"] not in TOOL_NAMES or type(raw["arguments"]) is not dict):
        raise ValueError("Invalid direct_call specification")
    return dict(raw)


CASE_BASE_FIELDS = frozenset({
    "id", "mode", "request", "max_steps", "max_tokens", "expected_status",
    "expected_model_steps", "expected_tokens_used",
    "expected_tool_invocations",
})
CASE_OPTIONAL_FIELDS = frozenset({
    "expected_answer", "direct_call", "expected_failure_code",
})


def parse_case(raw, seen):
    if type(raw) is not dict or not CASE_BASE_FIELDS <= set(raw):
        raise ValueError("Invalid case fields")
    if set(raw) - (CASE_BASE_FIELDS | CASE_OPTIONAL_FIELDS):
        raise ValueError("Invalid case fields")
    case_id = raw["id"]
    direct_call = raw.get("direct_call")
    if (type(case_id) is not str or not case_id or case_id in seen
            or raw["mode"] not in ("direct", "agent")
            or type(raw["request"]) is not str or not raw["request"]
            or not _non_negative_int(raw["max_steps"])
            or not _non_negative_int(raw["max_tokens"])
            or not _non_negative_int(raw["expected_model_steps"])
            or not _non_negative_int(raw["expected_tokens_used"])
            or not _non_negative_int(raw["expected_tool_invocations"])):
        raise ValueError("Invalid case specification")
    if raw["expected_status"] == "SUCCEEDED":
        answer = raw.get("expected_answer")
        if type(answer) is not str or not answer:
            raise ValueError(f"Case {case_id} must carry expected_answer")
        if raw.get("expected_failure_code") is not None:
            raise ValueError(f"Case {case_id} cannot define expected_failure_code on success")
        if raw["mode"] == "direct":
            if not isinstance(direct_call, dict):
                raise ValueError(f"Direct case {case_id} must define direct_call")
        elif direct_call is not None:
            raise ValueError(f"Agent case {case_id} cannot define direct_call")
    elif raw["expected_status"] == "FAILED":
        if raw["mode"] != "agent":
            raise ValueError(f"Failed case {case_id} must use agent mode")
        if raw.get("expected_failure_code") not in FAILURE_CODES:
            raise ValueError(f"Case {case_id} has an unsupported failure code")
        if raw.get("expected_answer") is not None or direct_call is not None:
            raise ValueError(f"Failed case {case_id} cannot define success-only fields")
    else:
        raise ValueError(f"Case {case_id} has an invalid expected_status")
    seen.add(case_id)
    return dict(raw)


def parse_scenario(raw):
    _fields(raw, ["schema_version", "scenario_id", "attribution", "cases"])
    if (raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID
            or type(raw["cases"]) is not list or len(raw["cases"]) != 8):
        raise ValueError("Invalid scenario projection")
    seen = set()
    cases = [parse_case(case, seen) for case in raw["cases"]]
    return {"schema_version": "1.0", "scenario_id": SCENARIO_ID,
            "cases": cases, "attribution": parse_attribution(raw["attribution"])}


def _parse_decision(raw):
    if type(raw) is not dict or type(raw.get("kind")) is not str:
        raise ValueError("Invalid model decision")
    if raw["kind"] == "final":
        _fields(raw, ["kind", "answer"])
        if type(raw["answer"]) is not str or not raw["answer"]:
            raise ValueError("Final decision must carry a non-empty answer")
        return dict(raw)
    if raw["kind"] == "tool_call":
        _fields(raw, ["kind", "call_id", "tool", "arguments"])
        if (type(raw["call_id"]) is not str or not raw["call_id"]
                or type(raw["tool"]) is not str or not raw["tool"]
                or type(raw["arguments"]) is not dict):
            raise ValueError("Invalid tool_call decision")
        return dict(raw)
    raise ValueError(f"Unknown decision kind: {raw['kind']}")


def parse_turn(raw):
    _fields(raw, ["schema_version", "decision", "usage"])
    _fields(raw["usage"], ["input_tokens", "output_tokens"])
    if (raw["schema_version"] != "1.0"
            or not _non_negative_int(raw["usage"]["input_tokens"])
            or not _non_negative_int(raw["usage"]["output_tokens"])):
        raise ValueError("Invalid model turn")
    return {"schema_version": "1.0", "decision": _parse_decision(raw["decision"]),
            "usage": dict(raw["usage"])}


def parse_fake_model(raw, scenario):
    _fields(raw, ["schema_version", "scenario_id", "trajectories"])
    if raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID:
        raise ValueError("Invalid fake-model projection")
    agent_cases = {case["id"] for case in scenario["cases"]
                   if case["mode"] == "agent"}
    trajectories = raw["trajectories"]
    if type(trajectories) is not dict or set(trajectories) != agent_cases:
        raise ValueError("Trajectories must cover exactly the agent cases")
    parsed = {}
    for case_id, turns in trajectories.items():
        if type(turns) is not list or not turns:
            raise ValueError(f"Trajectory {case_id} must be a non-empty list")
        parsed[case_id] = [parse_turn(turn) for turn in turns]
    return parsed


def _parse_tool_records(raw, label, pattern):
    if type(raw) is not dict:
        raise ValueError(f"Fake-tool fixture must define {label}")
    parsed = {}
    for identifier, entry in raw.items():
        if (type(identifier) is not str or pattern.fullmatch(identifier) is None
                or type(entry) is not dict):
            raise ValueError(f"Invalid {label} record: {identifier}")
        behavior = entry.get("behavior")
        if behavior is None:
            _fields(entry, ["output"])
            if type(entry["output"]) is not dict or not entry["output"]:
                raise ValueError(f"{label} {identifier} must carry output")
            parsed[identifier] = {"output": dict(entry["output"])}
        elif behavior in TOOL_BEHAVIORS:
            _fields(entry, ["behavior"])
            parsed[identifier] = {"behavior": behavior}
        else:
            raise ValueError(f"{label} {identifier} has an invalid behavior")
    return parsed


def parse_fake_tools(raw):
    _fields(raw, ["schema_version", "scenario_id", "orders", "shipments"])
    if raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID:
        raise ValueError("Invalid fake-tools projection")
    return {"orders": _parse_tool_records(raw["orders"], "Order", ORD_PATTERN),
            "shipments": _parse_tool_records(raw["shipments"], "Shipment",
                                             SHIPMENT_PATTERN)}


def load_scenario_projection():
    return parse_scenario(_load_json(PROJECTION_DIR / "scenario.json"))


def load_fake_model_projection(scenario=None):
    return parse_fake_model(_load_json(PROJECTION_DIR / "fake-model.json"),
                            load_scenario_projection() if scenario is None
                            else scenario)


def load_fake_tools_projection():
    return parse_fake_tools(_load_json(PROJECTION_DIR / "fake-tools.json"))


def load_attribution_projection():
    return parse_attribution(_load_json(PROJECTION_DIR / "attribution.json"))


def load_golden(case_key):
    """The M1 golden's result_projection: the parity target for one case."""
    if case_key not in PARITY_CASE_KEYS:
        raise ValueError(f"Unknown parity case: {case_key}")
    golden = _load_json(GOLDEN_DIR / f"{case_key}.json")
    if (type(golden) is not dict or golden.get("case_key") != case_key
            or type(golden.get("result_projection")) is not dict
            or "attribution" not in golden["result_projection"]):
        raise ValueError(f"Invalid golden projection: {case_key}")
    return golden["result_projection"]


def load_argument_schema(tool_name):
    """The closed argument schema for one tool (checked-in contract)."""
    if tool_name == "lookup_order":
        path = ORDER_ARGUMENTS_SCHEMA_PATH
    elif tool_name == "lookup_shipment":
        path = SHIPMENT_ARGUMENTS_SCHEMA_PATH
    else:
        raise ValueError(f"Unknown tool: {tool_name}")
    schema = _load_json(path)
    if type(schema) is not dict or schema.get("type") != "object":
        raise ValueError(f"Invalid argument schema: {tool_name}")
    return schema


@dataclass(frozen=True)
class RunCase:
    case_id: str
    mode: str
    request: str
    max_steps: int
    max_tokens: int
    turns: tuple
    direct_call: object
    fake_tools: dict
    latency_ms: dict
    price_table: dict


def load_case(case_id):
    """Assemble every run input for one parity case (strict, offline)."""
    scenario = load_scenario_projection()
    spec = next((case for case in scenario["cases"]
                 if case["id"] == case_id), None)
    if spec is None:
        raise ValueError(f"Unknown case: {case_id}")
    turns = () if spec["mode"] == "direct" else tuple(
        load_fake_model_projection(scenario)[case_id])
    tables = parse_attribution(scenario["attribution"])
    return RunCase(
        case_id=spec["id"], mode=spec["mode"], request=spec["request"],
        max_steps=spec["max_steps"], max_tokens=spec["max_tokens"],
        turns=turns, direct_call=spec.get("direct_call"),
        fake_tools=load_fake_tools_projection(),
        latency_ms=tables["latency_ms"], price_table=tables["price_table"])


if __name__ == "__main__":  # pragma: no cover - manual smoke only
    print(load_case("agent-delayed-shipment"))
