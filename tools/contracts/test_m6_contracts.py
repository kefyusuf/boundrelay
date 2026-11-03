"""M6 contracts: closed attribution schema, fixture price/latency tables, and
the event-surface audit map for all 38 canonical cases (M0:7, M1:8, M2:5,
M3:6, M4:6, M5:6).

Step names and event sequences were derived from each lesson's accepted
design spec, runner, and trace tests; M0 keys are '<case_id>@<mode>' because
the seven canonical M0 runs are case/mode combinations (each success route in
both modes plus the invalid-route case in model mode).
"""
from pathlib import Path
import json
import unittest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/observability/attribution.schema.json"
EVENT_SCHEMA_PATH = ROOT / "contracts/events/run-event.schema.json"
SCENARIOS = ("support-triage", "order-investigation", "support-handoff",
             "order-brief", "order-brief-recovery", "order-closure")
CASE_COUNTS = {"support-triage": 7, "order-investigation": 8,
               "support-handoff": 5, "order-brief": 6,
               "order-brief-recovery": 6, "order-closure": 6}
STEP_KINDS = ("read", "model_decision", "tool_call", "effect",
              "handoff", "route", "synthesis")
TERMINAL_TYPES = ("run.completed", "run.failed")
# Canonical step names each lesson's runner attributes (Task 2 wires these):
# M0 emits step.started with 'classify'/'specialist.<route>'; M1 and M2 emit
# no step.* events, so their attribution step names are fixed here ('model',
# 'tool.<tool>', 'classify', 'receiver.<receiver>'); M3-M5 emit
# 'worker.<id>'/'synthesize' (M5's effect submit is 'effect.submit').
EXPECTED_STEP_NAMES = {
    "support-triage": ("classify", "specialist.billing", "specialist.technical",
                       "specialist.general"),
    "order-investigation": ("model", "tool.lookup_order", "tool.lookup_shipment"),
    "support-handoff": ("classify", "receiver.billing-specialist",
                        "receiver.technical-specialist", "receiver.general-specialist"),
    "order-brief": ("worker.order-details", "worker.payment-status",
                    "worker.delivery-status", "synthesize"),
    "order-brief-recovery": ("worker.order-details", "worker.payment-status",
                             "worker.delivery-status", "synthesize"),
    "order-closure": ("worker.order-details", "worker.payment-status",
                      "worker.delivery-status", "effect.submit"),
}
# Price kinds each scenario's steps consume; every kind must be fixture-priced.
EXPECTED_STEP_KINDS = {
    "support-triage": ("read", "model_decision", "route"),
    "order-investigation": ("model_decision", "tool_call"),
    "support-handoff": ("route", "model_decision", "handoff"),
    "order-brief": ("read", "synthesis"),
    "order-brief-recovery": ("read", "synthesis"),
    "order-closure": ("read", "effect"),
}
EXPECTED_EVENT_SURFACE = {
    # M0 keys are '<case_id>@<mode>': the seven canonical runs are case/mode
    # combinations pinned by tools/parity/verify_m0.py.
    "support-triage": {
        "billing-duplicate-charge@deterministic": [
            "run.created", "run.started", "step.started", "route.selected",
            "step.completed", "step.started", "step.completed", "run.completed"],
        "billing-duplicate-charge@model": [
            "run.created", "run.started", "step.started", "model.requested",
            "model.completed", "route.selected", "step.completed",
            "step.started", "step.completed", "run.completed"],
        "technical-login-error@deterministic": [
            "run.created", "run.started", "step.started", "route.selected",
            "step.completed", "step.started", "step.completed", "run.completed"],
        "technical-login-error@model": [
            "run.created", "run.started", "step.started", "model.requested",
            "model.completed", "route.selected", "step.completed",
            "step.started", "step.completed", "run.completed"],
        "general-opening-hours@deterministic": [
            "run.created", "run.started", "step.started", "route.selected",
            "step.completed", "step.started", "step.completed", "run.completed"],
        "general-opening-hours@model": [
            "run.created", "run.started", "step.started", "model.requested",
            "model.completed", "route.selected", "step.completed",
            "step.started", "step.completed", "run.completed"],
        "invalid-model-route@model": [
            "run.created", "run.started", "step.started", "model.requested",
            "model.completed", "route.rejected", "step.failed", "run.failed"],
    },
    # M1: budget.consumed follows every completed model step; budget.exceeded
    # precedes run.failed on budget cases (after the triggering model step).
    "order-investigation": {
        "direct-order-status": [
            "run.created", "run.started", "tool.requested", "tool.completed",
            "run.completed"],
        "agent-delayed-shipment": [
            "run.created", "run.started",
            "model.requested", "model.completed", "budget.consumed",
            "tool.requested", "tool.completed",
            "model.requested", "model.completed", "budget.consumed",
            "tool.requested", "tool.completed",
            "model.requested", "model.completed", "budget.consumed",
            "run.completed"],
        "agent-unknown-tool": [
            "run.created", "run.started", "model.requested", "model.completed",
            "budget.consumed", "run.failed"],
        "agent-invalid-arguments": [
            "run.created", "run.started", "model.requested", "model.completed",
            "budget.consumed", "run.failed"],
        "agent-tool-timeout": [
            "run.created", "run.started", "model.requested", "model.completed",
            "budget.consumed", "tool.requested", "tool.failed", "run.failed"],
        "agent-tool-failure": [
            "run.created", "run.started", "model.requested", "model.completed",
            "budget.consumed", "tool.requested", "tool.failed", "run.failed"],
        "agent-step-budget": [
            "run.created", "run.started",
            "model.requested", "model.completed", "budget.consumed",
            "tool.requested", "tool.completed",
            "model.requested", "model.completed", "budget.consumed",
            "budget.exceeded", "run.failed"],
        "agent-token-budget": [
            "run.created", "run.started",
            "model.requested", "model.completed", "budget.consumed",
            "tool.requested", "tool.completed",
            "model.requested", "model.completed", "budget.consumed",
            "budget.exceeded", "run.failed"],
    },
    # M2: code router mode skips the model events; a rejected handoff ends
    # handoff.requested -> handoff.rejected -> run.failed.
    "support-handoff": {
        "code-billing-handoff": [
            "run.created", "run.started", "route.selected", "handoff.requested",
            "handoff.accepted", "run.completed"],
        "model-technical-handoff": [
            "run.created", "run.started", "model.requested", "model.completed",
            "route.selected", "handoff.requested", "handoff.accepted",
            "run.completed"],
        "model-low-confidence-fallback": [
            "run.created", "run.started", "model.requested", "model.completed",
            "route.selected", "handoff.requested", "handoff.accepted",
            "run.completed"],
        "handoff-context-loss": [
            "run.created", "run.started", "model.requested", "model.completed",
            "route.selected", "handoff.requested", "handoff.rejected",
            "run.failed"],
        "handoff-receiver-unavailable": [
            "run.created", "run.started", "route.selected", "handoff.requested",
            "handoff.rejected", "run.failed"],
    },
    # M3: parallel worker events interleave under concurrency 2 exactly as the
    # scripted completion orders schedule them; synthesize runs only when at
    # least one worker succeeded.
    "order-brief": {
        "sequential-complete": [
            "run.created", "run.started",
            "step.started", "step.completed", "step.started", "step.completed",
            "step.started", "step.completed",
            "step.started", "step.completed", "run.completed"],
        "parallel-complete": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "step.completed",
            "step.started", "step.completed", "step.started", "step.completed",
            "run.completed"],
        "parallel-out-of-order": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed",
            "step.started", "step.completed", "step.completed",
            "step.started", "step.completed", "run.completed"],
        "parallel-partial-failure": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "step.completed",
            "step.started", "step.failed",
            "step.started", "step.completed", "run.completed"],
        "parallel-all-failed": [
            "run.created", "run.started",
            "step.started", "step.started", "step.failed", "step.failed",
            "step.started", "step.failed", "run.failed"],
        "parallel-invalid-output": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "step.failed",
            "step.started", "step.completed", "step.started", "step.completed",
            "run.completed"],
    },
    # M4: multi-phase unions in phase order; crash phases emit no terminal,
    # resumed phases re-emit run.created/run.started plus checkpoint.restored;
    # the corrupt-state case's tooling-failure phase emits no events.
    "order-brief-recovery": {
        "parallel-clean-complete": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "run.completed"],
        "parallel-crash-resume": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "run.created", "run.started", "checkpoint.restored",
            "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "run.completed"],
        "parallel-crash-resume-partial": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "run.created", "run.started", "checkpoint.restored",
            "step.started", "step.completed", "run.completed"],
        "parallel-cancel-resume": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved", "run.cancelled",
            "run.created", "run.started", "checkpoint.restored",
            "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "run.completed"],
        "parallel-replay-from-checkpoint": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "run.completed",
            "run.created", "run.started", "checkpoint.restored",
            "step.started", "step.started",
            "step.completed", "checkpoint.saved", "step.completed",
            "checkpoint.saved",
            "step.started", "step.completed", "run.completed"],
        "parallel-corrupt-state": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "run.completed"],
    },
    # M5: approval precedes submission; the submit step uses tool.* events;
    # UNKNOWN (sink-unavailable) stays unflattened behind run.completed;
    # duplicate-key-suppressed unions the fresh run and the adopted rerun.
    "order-closure": {
        "approval-granted-effect-once": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.granted",
            "tool.requested", "tool.completed", "run.completed"],
        "approval-rejected-no-effect": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.rejected", "run.failed"],
        "retry-before-submit": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.granted",
            "run.created", "run.started",
            "approval.requested", "approval.granted",
            "tool.requested", "tool.completed", "run.completed"],
        "crash-submit-window-resolved": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.granted", "tool.requested",
            "run.created", "run.started", "run.completed"],
        "sink-unavailable-unknown": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.granted", "tool.requested",
            "run.created", "run.started", "run.completed"],
        "duplicate-key-suppressed": [
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.granted",
            "tool.requested", "tool.completed", "run.completed",
            "run.created", "run.started",
            "step.started", "step.started", "step.completed", "checkpoint.saved",
            "step.started", "step.completed", "checkpoint.saved",
            "step.completed", "checkpoint.saved",
            "approval.requested", "approval.granted",
            "tool.requested", "tool.completed", "run.completed"],
    },
}


def scenario_document(name):
    path = ROOT / f"fixtures/scenarios/{name}.yaml"
    if not path.exists():
        raise AssertionError(f"Missing scenario fixture: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fixture_case_ids(name):
    key = "case_id" if name in ("order-brief", "order-brief-recovery",
                                "order-closure") else "id"
    return [case[key] for case in scenario_document(name)["cases"]]


def m0_case_keys():
    keys = []
    for case in scenario_document("support-triage")["cases"]:
        if "expected_route" in case:
            keys += [f"{case['id']}@deterministic", f"{case['id']}@model"]
        elif case.get("expected_failure_code") == "INVALID_ROUTE_DECISION":
            keys += [f"{case['id']}@model"]
        else:
            raise AssertionError(f"Unsupported M0 case expectation: {case}")
    return keys


def event_type_enum():
    schema = json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return set(schema["properties"]["type"]["enum"])


def attribution_table(name):
    table = scenario_document(name).get("attribution")
    if not isinstance(table, dict):
        raise AssertionError(f"{name}: missing attribution table")
    return table


def int_table(table, label):
    if not isinstance(table, dict):
        raise AssertionError(f"{label} must be an object")
    for key, value in table.items():
        if type(value) is not int or value < 0:
            raise AssertionError(f"{label}[{key}] must be a deterministic int >= 0, got {value!r}")
    return table


def attribution_validator():
    if not SCHEMA_PATH.exists():
        raise AssertionError(f"Missing M6 contract: {SCHEMA_PATH.relative_to(ROOT)}")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def attribution_sample():
    return {"steps": [{"step_name": "worker.order-details", "latency_ms": 10,
                       "cost_cents": 0, "attempts": 1}],
            "totals": {"latency_ms": 10, "cost_cents": 0, "attempts": 1}}


class M6AttributionContractTests(unittest.TestCase):
    def test_attribution_schema_and_tables(self):
        check = attribution_validator()
        self.assertTrue(check.is_valid(attribution_sample()))
        negatives = []
        for mutate in [
            lambda b: b.update(extra=1),
            lambda b: b.pop("totals"),
            lambda b: b.update(steps=[]),
            lambda b: b.update(steps="one"),
            lambda b: b["steps"][0].update(extra=1),
            lambda b: b["steps"][0].pop("attempts"),
            lambda b: b["steps"][0].update(step_name=""),
            lambda b: b["steps"][0].update(step_name=7),
            lambda b: b["steps"][0].update(latency_ms=-1),
            lambda b: b["steps"][0].update(cost_cents=-1),
            lambda b: b["steps"][0].update(attempts=0),
            lambda b: b["steps"][0].update(latency_ms=10.5),
            lambda b: b["steps"][0].update(attempts=True),
            lambda b: b["totals"].update(extra=1),
            lambda b: b["totals"].update(attempts=0),
            lambda b: b["totals"].update(latency_ms=-2),
            lambda b: b["totals"].pop("cost_cents"),
            lambda b: b["totals"].update(cost_cents=1.5),
        ]:
            bad = attribution_sample()
            mutate(bad)
            negatives.append(bad)
        for invalid in negatives:
            self.assertFalse(check.is_valid(invalid), invalid)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        fragments = [schema, schema["properties"]["steps"]["items"],
                     schema["properties"]["totals"]]
        for fragment in fragments:
            self.assertIs(fragment.get("additionalProperties"), False, fragment)
            self.assertEqual(fragment.get("type"), "object")
        self.assertEqual(schema.get("$schema"),
                         "https://json-schema.org/draft/2020-12/schema")
        self.assertGreaterEqual(schema["properties"]["steps"].get("minItems", 0), 1)
        for scenario in SCENARIOS:
            table = attribution_table(scenario)
            latency = int_table(table.get("latency_ms"),
                                f"{scenario}.attribution.latency_ms")
            prices = int_table(table.get("price_table"),
                               f"{scenario}.attribution.price_table")
            expected_names = EXPECTED_STEP_NAMES.get(scenario, set())
            self.assertEqual(
                set(latency), set(expected_names),
                f"{scenario}: latency table must cover exactly the runner's step names")
            unknown = set(prices) - set(STEP_KINDS)
            self.assertEqual(unknown, set(),
                             f"{scenario}: unknown price kinds {unknown}")
            for kind in EXPECTED_STEP_KINDS.get(scenario, set()):
                self.assertIn(kind, prices,
                              f"{scenario}: missing price for kind {kind}")
            if "read" in prices:
                self.assertEqual(prices["read"], 0, "reads cost zero")


class M6EventSurfaceAuditTests(unittest.TestCase):
    def test_event_surface_audit(self):
        surface = EXPECTED_EVENT_SURFACE
        self.assertEqual(set(surface), set(SCENARIOS),
                         "audit map must cover exactly the six scenarios")
        total = sum(len(cases) for cases in surface.values())
        self.assertEqual(total, 38, f"audit map must cover 38 cases, got {total}")
        enum = event_type_enum()
        for scenario in SCENARIOS:
            cases = surface.get(scenario, {})
            self.assertEqual(
                len(cases), CASE_COUNTS[scenario],
                f"{scenario}: expected {CASE_COUNTS[scenario]} canonical cases")
            if scenario == "support-triage":
                self.assertEqual(list(cases), m0_case_keys())
            else:
                self.assertEqual(list(cases), fixture_case_ids(scenario))
            for case_id, types in cases.items():
                self.assertTrue(types, f"{scenario}/{case_id}: empty event list")
                self.assertEqual(types[0], "run.created",
                                 f"{scenario}/{case_id} must start run.created")
                self.assertIn(types[-1], TERMINAL_TYPES,
                              f"{scenario}/{case_id} must end with a terminal")
                drifted = [t for t in types if t not in enum]
                self.assertEqual(
                    drifted, [],
                    f"{scenario}/{case_id}: event types outside the envelope enum: {drifted}")


if __name__ == "__main__":
    unittest.main()
