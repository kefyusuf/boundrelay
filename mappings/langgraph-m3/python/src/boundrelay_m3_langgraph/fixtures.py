"""Strict fixture loading for the M8 mapping: checked-in artifacts only.

Reads the canonical Go fixture projections
(fixtures/goprojections/order-brief/{scenario,workers,attribution}.json)
and the M3 goldens' result projections (fixtures/goldens/order-brief/).
No YAML, no network, no mutation of the sources.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
PROJECTION_DIR = ROOT / "fixtures/goprojections/order-brief"
GOLDEN_DIR = ROOT / "fixtures/goldens/order-brief"
WORKER_IDS = ("order-details", "payment-status", "delivery-status")
SCENARIO_ID = "order-brief"
ORD_PATTERN = re.compile(r"ORD-[0-9]{4}")
STEP_KINDS = ("read", "model_decision", "tool_call", "effect", "handoff",
              "route", "synthesis")
PARITY_CASE_KEYS = (
    "sequential-complete", "parallel-complete", "parallel-out-of-order",
    "parallel-partial-failure", "parallel-all-failed",
    "parallel-invalid-output",
)


def _fields(raw, keys):
    if type(raw) is not dict or set(raw) != set(keys):
        raise ValueError("Invalid fixture fields")
    return raw


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid fixture document: {path.name}") from error


def _is_ord(value):
    return type(value) is str and ORD_PATTERN.fullmatch(value) is not None


def _valid_latency(raw):
    return (type(raw) is dict and bool(raw) and all(
        type(key) is str and key and type(value) is int and value >= 0
        for key, value in raw.items()))


def _valid_price_table(raw):
    return (type(raw) is dict and bool(raw) and all(
        key in STEP_KINDS and type(value) is int and value >= 0
        for key, value in raw.items())
        and ("read" not in raw or raw["read"] == 0))
def parse_attribution(raw):
    _fields(raw, ["latency_ms", "price_table"])
    if not _valid_latency(raw["latency_ms"]):
        raise ValueError("Invalid attribution latency table")
    if not _valid_price_table(raw["price_table"]):
        raise ValueError("Invalid attribution price table")
    return {"latency_ms": dict(raw["latency_ms"]),
            "price_table": dict(raw["price_table"])}


def _valid_instruction(instruction):
    if type(instruction) is not dict:
        return False
    if instruction.get("operation") == "return":
        _fields(instruction, ["operation", "output"])
        output = instruction["output"]
        # The output itself may be deliberately invalid (the invalid-output
        # case); only the envelope is validated here. Output shape is judged
        # inside the worker node (INVALID_WORKER_OUTPUT path).
        return (type(output) is dict and "order_id" in output
                and _is_ord(output["order_id"]))
    if instruction.get("operation") == "raise":
        _fields(instruction, ["operation", "failure_code"])
        return instruction["failure_code"] == "WORKER_EXECUTION_FAILED"
    return False


def parse_workers(raw, scenario):
    refs = {case["worker_fixture"] for case in scenario["cases"]}
    if type(raw) is not dict or set(raw) != refs:
        raise ValueError("Workers projection must cover exactly the fixtures")
    for ref, fixture in raw.items():
        _fields(fixture, WORKER_IDS)
        for instruction in fixture.values():
            if not _valid_instruction(instruction):
                raise ValueError(f"Invalid worker instruction in {ref}")
    return raw


def _feasible(order, mode):
    active, pending = set(), list(WORKER_IDS)
    limit = 1 if mode == "sequential" else 2
    for next_id in order:
        while len(active) < limit and pending:
            active.add(pending.pop(0))
        if next_id not in active:
            return False
        active.remove(next_id)
    return True


def parse_case(raw, seen):
    _fields(raw, ["case_id", "execution_mode", "worker_fixture",
                  "completion_order"])
    order = raw["completion_order"]
    if (type(raw["case_id"]) is not str or not raw["case_id"]
            or raw["case_id"] in seen
            or raw["execution_mode"] not in ("sequential", "parallel")
            or type(order) is not list or len(order) != 3
            or any(worker_id not in WORKER_IDS for worker_id in order)
            or sorted(order) != sorted(WORKER_IDS)
            or not _feasible(order, raw["execution_mode"])):
        raise ValueError("Invalid case specification")
    seen.add(raw["case_id"])
    return dict(raw)


def parse_scenario(raw):
    _fields(raw, ["schema_version", "scenario_id", "order_id", "cases",
                  "attribution"])
    if (raw["schema_version"] != "1.0" or raw["scenario_id"] != SCENARIO_ID
            or not _is_ord(raw["order_id"]) or type(raw["cases"]) is not list
            or len(raw["cases"]) != 6):
        raise ValueError("Invalid scenario projection")
    seen = set()
    cases = [parse_case(case, seen) for case in raw["cases"]]
    return {"schema_version": "1.0", "scenario_id": SCENARIO_ID,
            "order_id": raw["order_id"], "cases": cases,
            "attribution": parse_attribution(raw["attribution"])}


def load_scenario_projection():
    return parse_scenario(_load_json(PROJECTION_DIR / "scenario.json"))


def load_workers_projection():
    raw = _load_json(PROJECTION_DIR / "workers.json")
    return parse_workers(raw, load_scenario_projection())


def load_attribution_projection():
    return parse_attribution(_load_json(PROJECTION_DIR / "attribution.json"))
def load_golden(case_key):
    """The M3 golden's result_projection: the parity target for one case."""
    if case_key not in PARITY_CASE_KEYS:
        raise ValueError(f"Unknown parity case: {case_key}")
    golden = _load_json(GOLDEN_DIR / f"{case_key}.json")
    if (type(golden) is not dict or golden.get("case_key") != case_key
            or type(golden.get("result_projection")) is not dict
            or "attribution" not in golden["result_projection"]):
        raise ValueError(f"Invalid golden projection: {case_key}")
    return golden["result_projection"]


@dataclass(frozen=True)
class RunCase:
    case_id: str
    execution_mode: str
    completion_order: tuple
    instructions: dict
    order_id: str
    latency_ms: dict
    price_table: dict

    @property
    def limit(self):
        return 1 if self.execution_mode == "sequential" else 2
def load_case(case_id):
    """Assemble every run input for one parity case (strict, offline)."""
    scenario = load_scenario_projection()
    spec = next((case for case in scenario["cases"]
                 if case["case_id"] == case_id), None)
    if spec is None:
        raise ValueError(f"Unknown case: {case_id}")
    workers = load_workers_projection()
    tables = parse_attribution(scenario["attribution"])
    return RunCase(
        case_id=spec["case_id"], execution_mode=spec["execution_mode"],
        completion_order=tuple(spec["completion_order"]),
        instructions=workers[spec["worker_fixture"]],
        order_id=scenario["order_id"], latency_ms=tables["latency_ms"],
        price_table=tables["price_table"])


if __name__ == "__main__":  # pragma: no cover - manual smoke only
    print(load_case("parallel-complete"))
