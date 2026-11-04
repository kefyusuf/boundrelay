"""M7 contracts: Go fixture projections, the 13 canonical M0/M3 case keys,
and the Go module pins.

Projections (fixtures/goprojections/<scenario>/{scenario,workers,attribution}
.json) must deep-equal the YAML sources they were generated from. The Go
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
GO_SCENARIOS = ("support-triage", "order-brief")
MIN_GO_PARTS = (1, 25)
EXPECTED_MODULE = "module github.com/kefyusuf/boundrelay/go"
# The canonical three-language evaluation set (M6's EXPECTED_EVENT_SURFACE
# covers the same 13 M0/M3 keys).
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
