"""M7 contracts: Go fixture projections, the 13 canonical M0/M3 case keys,
the 8 canonical M1 (order-investigation) case keys, the 5 canonical M2
(support-handoff) case keys, the 6 canonical M4 (order-brief-recovery) case
keys, the 6 canonical M5 (order-closure) case keys, and the Go module pins.

Projections (fixtures/goprojections/<scenario>/...) must deep-equal the YAML
sources they were generated from: scenario.json and attribution.json for
every Go scenario, plus per-scenario scripts — workers.json for M0/M3/M4/M5
(the referenced worker fixtures), fake-model.json/fake-tools.json for M1 (the
scripted fake-model turns exactly as the TS/Py provider replays them, i.e.
each trajectory entry's `return` value, and the orders/shipments data behind
the fake tool registry), and fake-model.json/failures.json for M2 (the
scripted route decisions exactly as the TS/Py ScriptedRouteProvider replays
them, i.e. each decision entry's `return` value, and the handoff failure
fixtures behind the receivers' availability and context validation). The Go
module pins Go >= 1.25 in go.mod, and GO_VERSION must carry that directive.
M0 keys are '<case_id>@<mode>' per the verify_m0 rule (success routes in both
modes, the INVALID_ROUTE_DECISION case in model mode only).
"""
from pathlib import Path
import json
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
GO_PROJECTION_ROOT = ROOT / "fixtures/goprojections"
GO_ROOT = ROOT / "go"
GO_SCENARIOS = ("support-triage", "order-brief", "order-investigation",
                "support-handoff", "order-brief-recovery", "order-closure")
MIN_GO_PARTS = (1, 25)
EXPECTED_MODULE = "module github.com/kefyusuf/boundrelay/go"
# The canonical M0/M3 three-language evaluation set (M6's
# EXPECTED_EVENT_SURFACE covers the same 13 M0/M3 keys).
EXPECTED_CASE_KEYS = (
    "billing-duplicate-charge@deterministic",
    "billing-duplicate-charge@model",
    "technical-login-error@deterministic",
    "technical-login-error@model",
    "general-opening-hours@deterministic",
    "general-opening-hours@model",
    "invalid-model-route@model",
    "sequential-complete",
    "parallel-complete",
    "parallel-out-of-order",
    "parallel-partial-failure",
    "parallel-all-failed",
    "parallel-invalid-output",
)
# The canonical M1 case keys (goldens are named by case id; the mode is
# canonical per case — direct for direct-order-status, agent otherwise).
EXPECTED_M1_CASE_KEYS = (
    "direct-order-status",
    "agent-delayed-shipment",
    "agent-unknown-tool",
    "agent-invalid-arguments",
    "agent-tool-timeout",
    "agent-tool-failure",
    "agent-step-budget",
    "agent-token-budget",
)
# The canonical M2 case keys (goldens are named by case id; the router mode
# is canonical per case — code for the code-*/handoff-receiver-unavailable
# cases, model otherwise).
EXPECTED_M2_CASE_KEYS = (
    "code-billing-handoff",
    "model-technical-handoff",
    "model-low-confidence-fallback",
    "handoff-context-loss",
    "handoff-receiver-unavailable",
)
# The canonical M4 case keys (goldens are named by case id; every case is
# parallel and carries at most one scripted control/extension).
EXPECTED_M4_CASE_KEYS = (
    "parallel-clean-complete",
    "parallel-crash-resume",
    "parallel-crash-resume-partial",
    "parallel-cancel-resume",
    "parallel-replay-from-checkpoint",
    "parallel-corrupt-state",
)
# The canonical M5 case keys (goldens are named by case id; every case is
# parallel, carries the fixture approval block, and at most one scripted
# control extension).
EXPECTED_M5_CASE_KEYS = (
    "approval-granted-effect-once",
    "approval-rejected-no-effect",
    "retry-before-submit",
    "crash-submit-window-resolved",
    "sink-unavailable-unknown",
    "duplicate-key-suppressed",
)


def scenario_document(name):
    path = ROOT / f"fixtures/scenarios/{name}.yaml"
    if not path.exists():
        raise AssertionError(f"Missing scenario fixture: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_projection(scenario, name):
    path = GO_PROJECTION_ROOT / scenario / name
    if not path.exists():
        raise AssertionError(f"Missing Go projection: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def worker_fixture_refs(name):
    """Ordered unique worker fixtures referenced by the scenario's cases."""
    refs = []
    for case in scenario_document(name).get("cases", []):
        ref = case.get("worker_fixture")
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def m0_case_keys():
    """The verify_m0 rule: case@mode for the seven canonical M0 runs."""
    keys = []
    for case in scenario_document("support-triage")["cases"]:
        if "expected_route" in case:
            keys += [f"{case['id']}@deterministic", f"{case['id']}@model"]
        elif case.get("expected_failure_code") == "INVALID_ROUTE_DECISION":
            keys += [f"{case['id']}@model"]
        else:
            raise AssertionError(f"Unsupported M0 case expectation: {case}")
    return keys


def go_mod_text():
    path = GO_ROOT / "go.mod"
    if not path.exists():
        raise AssertionError(f"Missing Go module pin: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def go_directive(text):
    """The go.mod 'go <version>' directive and its numeric parts."""
    match = re.search(r"(?m)^go (\d+(?:\.\d+){0,2})$", text)
    if not match:
        raise AssertionError("go.mod carries no 'go <version>' directive")
    version = match.group(1)
    return version, tuple(int(part) for part in version.split("."))


def fake_model_document(scenario_id):
    path = ROOT / f"fixtures/fake-model/{scenario_id}.yaml"
    if not path.exists():
        raise AssertionError(f"Missing fake-model fixture: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fake_tool_document(scenario_id):
    path = ROOT / f"fixtures/fake-tools/{scenario_id}.yaml"
    if not path.exists():
        raise AssertionError(f"Missing fake-tools fixture: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def failure_fixture_document(scenario_id):
    path = ROOT / f"fixtures/failures/{scenario_id}.yaml"
    if not path.exists():
        raise AssertionError(f"Missing failures fixture: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def projected_model_turns(document):
    """The fake-model turns exactly as the TS/Py ScriptedModelProvider
    replays them: each trajectory entry's `return` value."""
    turns = {}
    for case_id, entries in document["trajectories"].items():
        projected = []
        for entry in entries:
            if not isinstance(entry, dict) or "return" not in entry:
                raise AssertionError(
                    f"trajectory {case_id} entries must carry return values")
            projected.append(entry["return"])
        turns[case_id] = projected
    return turns


def projected_route_decisions(document):
    """The fake-model decisions exactly as the TS/Py ScriptedRouteProvider
    replays them: each decision entry's `return` value."""
    decisions = {}
    for case_id, entry in document["decisions"].items():
        if not isinstance(entry, dict) or set(entry) != {"return"}:
            raise AssertionError(
                f"decision {case_id} must contain exactly return")
        decisions[case_id] = entry["return"]
    return decisions


class M7ProjectionContractTests(unittest.TestCase):
    def test_projections_match_yaml_sources(self):
        for name in GO_SCENARIOS:
            source = scenario_document(name)
            self.assertEqual(
                load_projection(name, "scenario.json"), source,
                f"{name}: scenario projection drifts from the YAML source")
            self.assertEqual(
                load_projection(name, "attribution.json"), source["attribution"],
                f"{name}: attribution projection drifts from the YAML source")
            if name == "order-investigation":
                fake_model = load_projection(name, "fake-model.json")
                model_source = fake_model_document(name)
                self.assertEqual(fake_model["schema_version"], "1.0",
                                 "fake-model projection must carry the 1.0 header")
                self.assertEqual(fake_model["scenario_id"], name,
                                 "fake-model projection must carry the scenario id")
                self.assertEqual(
                    fake_model["trajectories"], projected_model_turns(model_source),
                    "fake-model turns projection drifts from the YAML source")
                self.assertEqual(
                    load_projection(name, "fake-tools.json"), fake_tool_document(name),
                    f"{name}: fake-tools projection drifts from the YAML source")
                continue
            if name == "support-handoff":
                fake_model = load_projection(name, "fake-model.json")
                model_source = fake_model_document(name)
                self.assertEqual(fake_model["schema_version"], "1.0",
                                 "fake-model projection must carry the 1.0 header")
                self.assertEqual(fake_model["scenario_id"], name,
                                 "fake-model projection must carry the scenario id")
                self.assertEqual(
                    fake_model["decisions"], projected_route_decisions(model_source),
                    "fake-model decisions projection drifts from the YAML source")
                self.assertEqual(
                    load_projection(name, "failures.json"), failure_fixture_document(name),
                    f"{name}: failures projection drifts from the YAML source")
                continue
            workers = load_projection(name, "workers.json")
            refs = worker_fixture_refs(name)
            self.assertEqual(
                sorted(workers), sorted(refs),
                f"{name}: workers map must cover exactly the referenced fixtures")
            for ref, content in workers.items():
                fixture = yaml.safe_load((ROOT / ref).read_text(encoding="utf-8"))
                self.assertEqual(
                    content, fixture,
                    f"{name}: worker projection {ref} drifts from the YAML source")

    def test_m4_case_keys_enumerated(self):
        scenario = scenario_document("order-brief-recovery")
        keys = tuple(case["case_id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 6, "the canonical M4 set is 6 case keys")
        self.assertEqual(keys, EXPECTED_M4_CASE_KEYS,
                         "M4 case keys drifted from the canonical set")
        for case in scenario["cases"]:
            self.assertEqual(case["execution_mode"], "parallel",
                             "every M4 case is a parallel case")
            extension = sum(1 for field in ("controls", "replay_from_step",
                                            "tampered_state") if field in case)
            self.assertLessEqual(extension, 1,
                                 "M4 cases carry at most one scripted extension")
        self.assertEqual(scenario["order_id"], "ORD-1001")
        for key in keys:
            golden_path = ROOT / f"fixtures/goldens/order-brief-recovery/{key}.json"
            self.assertTrue(golden_path.exists(),
                            f"missing golden for pinned M4 key {key}")

    def test_m5_case_keys_enumerated(self):
        scenario = scenario_document("order-closure")
        keys = tuple(case["case_id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 6, "the canonical M5 set is 6 case keys")
        self.assertEqual(keys, EXPECTED_M5_CASE_KEYS,
                         "M5 case keys drifted from the canonical set")
        for case in scenario["cases"]:
            self.assertEqual(case["execution_mode"], "parallel",
                             "every M5 case is a parallel case")
            self.assertIn("approval", case,
                          "every M5 case binds a fixture approval decision")
            extension = sum(1 for field in ("controls", "duplicate_key")
                            if field in case)
            self.assertLessEqual(extension, 1,
                                 "M5 cases carry at most one scripted extension")
        self.assertEqual(scenario["order_id"], "ORD-1001")
        for key in keys:
            golden_path = ROOT / f"fixtures/goldens/order-closure/{key}.json"
            self.assertTrue(golden_path.exists(),
                            f"missing golden for pinned M5 key {key}")

    def test_m1_case_keys_enumerated(self):
        scenario = scenario_document("order-investigation")
        keys = tuple(case["id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 8, "the canonical M1 set is 8 case keys")
        self.assertEqual(keys, EXPECTED_M1_CASE_KEYS,
                         "M1 case keys drifted from the canonical set")
        modes = {case["id"]: case["mode"] for case in scenario["cases"]}
        self.assertEqual(modes["direct-order-status"], "direct",
                         "direct-order-status is the canonical direct case")
        for key in keys[1:]:
            self.assertEqual(modes[key], "agent", f"{key} must be an agent case")
        for key in keys:
            golden_path = ROOT / f"fixtures/goldens/order-investigation/{key}.json"
            self.assertTrue(golden_path.exists(),
                            f"missing golden for pinned M1 key {key}")

    def test_m2_case_keys_enumerated(self):
        scenario = scenario_document("support-handoff")
        keys = tuple(case["id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 5, "the canonical M2 set is 5 case keys")
        self.assertEqual(keys, EXPECTED_M2_CASE_KEYS,
                         "M2 case keys drifted from the canonical set")
        modes = {case["id"]: case["router_mode"] for case in scenario["cases"]}
        self.assertEqual(modes["code-billing-handoff"], "code",
                         "code-billing-handoff is the canonical code case")
        self.assertEqual(modes["handoff-receiver-unavailable"], "code",
                         "handoff-receiver-unavailable is a canonical code case")
        for key in ("model-technical-handoff", "model-low-confidence-fallback",
                    "handoff-context-loss"):
            self.assertEqual(modes[key], "model", f"{key} must be a model case")
        self.assertEqual(scenario["confidence_threshold"], 0.80,
                         "the M2 policy threshold is fixed at 0.80")
        for key in keys:
            golden_path = ROOT / f"fixtures/goldens/support-handoff/{key}.json"
            self.assertTrue(golden_path.exists(),
                            f"missing golden for pinned M2 key {key}")


class M7CaseKeyEnumerationTests(unittest.TestCase):
    def test_case_keys_enumerated(self):
        keys = m0_case_keys() + [case["case_id"] for
                                 case in scenario_document("order-brief")["cases"]]
        self.assertEqual(len(keys), 13,
                         "the canonical M0/M3 set is 13 case keys")
        self.assertEqual(len(set(keys)), 13, "case keys must be unique")
        self.assertEqual(tuple(keys), EXPECTED_CASE_KEYS,
                         "enumerated keys drifted from the canonical set")


class M7ModulePinTests(unittest.TestCase):
    def test_go_module_pins(self):
        text = go_mod_text()
        self.assertIn(EXPECTED_MODULE, text,
                      "go.mod must declare the boundrelay Go module path")
        version, parts = go_directive(text)
        self.assertGreaterEqual(parts, MIN_GO_PARTS,
                                f"Go {version} is below the 1.25 floor")
        version_file = GO_ROOT / "GO_VERSION"
        self.assertTrue(version_file.exists(),
                        "missing go/GO_VERSION pin file")
        self.assertEqual(version_file.read_text(encoding="utf-8").strip(), version,
                         "GO_VERSION must equal the go.mod go directive")


if __name__ == "__main__":
    unittest.main()
