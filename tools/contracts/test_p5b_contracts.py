"""P5b contracts: google-adk dependency isolation, the mapping manifest,
and the five canonical M2 parity case keys.

Isolation: the pinned Google ADK distribution ('google-adk', import
package 'google.adk') and the mapping package names must not appear in
any file under lessons/, contracts/, tools/, scripts/, or go/ outside
the precise allowlist below (this proving test). Two probes, both
fail-closed:
  1. a case-insensitive substring scan for the distinctive distribution
     and mapping-package tokens (mirrors the P5a/M8 scans); and
  2. a Python import scan: no module under the scan roots may execute
     'import google' / 'from google ...' (the bare SDK import root,
     which a substring scan cannot target without false positives).

Manifest: mappings/adk-m2/python/pyproject.toml must name the package
boundrelay-m2-adk, and requirements-dev.txt must pin google-adk==2.13.0
exactly with no other framework dependency (only the shared jsonschema
dev pin may accompany it).

Parity keys: the five canonical support-handoff cases are enumerated
and each has an M2 golden projection whose result_projection is the
parity target.
"""
from pathlib import Path
import json
import re
import tomllib
import unittest
from importlib import metadata

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("lessons", "contracts", "tools", "scripts", "go")
# Case-insensitive: the hyphenated dist spelling, the underscored dist
# name, and the mapping package names. The bare import root ('google')
# is covered by the import scan below, not by substrings.
ISOLATION_TOKENS = (
    "google-adk", "google_adk",
    "boundrelay_m2_adk", "boundrelay-m2-adk",
)
IMPORT_SCAN_PATTERN = re.compile(
    r"(?m)^\s*(?:import|from)\s+google\b")
ISOLATION_ALLOWLIST = (
    "tools/contracts/test_p5b_contracts.py",
)
MAPPING_PYTHON = ROOT / "mappings/adk-m2/python"
EXPECTED_PACKAGE_NAME = "boundrelay-m2-adk"
EXPECTED_SDK_PIN = "google-adk==2.13.0"
ALLOWED_REQUIREMENTS = frozenset({
    "google-adk==2.13.0",
    "jsonschema[format]==4.26.0",
})
PARITY_CASE_KEYS = (
    "code-billing-handoff",
    "model-technical-handoff",
    "model-low-confidence-fallback",
    "handoff-context-loss",
    "handoff-receiver-unavailable",
)
MAPPING_MODULES = (
    "__init__.py", "fixtures.py", "results.py", "attribution.py",
    "mapping.py", "cli.py",
)


def is_allowlisted(key):
    if key in ISOLATION_ALLOWLIST:
        return True
    # Compiled bytecode of an allowlisted source is the same artifact.
    parent, name = key.rsplit("/", 1)
    if parent.endswith("__pycache__") and name.endswith(".pyc"):
        stem = name.split(".", 1)[0] + ".py"
        source = f"{parent[: -len('__pycache__')]}{stem}"
        return source in ISOLATION_ALLOWLIST
    return False


def iter_scan_files():
    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            raise AssertionError(f"Missing scan root: {base}")
        for path in sorted(base.rglob("*")):
            if path.is_file():
                yield path


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise AssertionError(f"Unreadable scan target: {path}") from error


class P5bIsolationContractTests(unittest.TestCase):
    def test_no_sdk_or_mapping_tokens_outside_the_mapping(self):
        offenders = []
        for path in iter_scan_files():
            key = path.relative_to(ROOT).as_posix()
            if is_allowlisted(key):
                continue
            text = read_text(path).lower()
            if any(token in text for token in ISOLATION_TOKENS):
                offenders.append(key)
        self.assertEqual(
            offenders, [],
            "google-adk/mapping references outside mappings/adk-m2/ "
            "(and outside the precise allowlist) break P5b isolation")

    def test_no_bare_sdk_imports_outside_the_mapping(self):
        offenders = []
        for path in iter_scan_files():
            key = path.relative_to(ROOT).as_posix()
            if is_allowlisted(key) or path.suffix != ".py":
                continue
            if IMPORT_SCAN_PATTERN.search(read_text(path)):
                offenders.append(key)
        self.assertEqual(
            offenders, [],
            "the google.adk SDK modules must not be imported outside "
            "mappings/adk-m2/ (and outside the precise allowlist)")


class P5bManifestContractTests(unittest.TestCase):
    def test_pyproject_names_the_mapping_package(self):
        path = MAPPING_PYTHON / "pyproject.toml"
        self.assertTrue(path.exists(), f"missing mapping manifest: {path}")
        with path.open("rb") as handle:
            manifest = tomllib.load(handle)
        self.assertEqual(
            manifest.get("project", {}).get("name"), EXPECTED_PACKAGE_NAME,
            "mapping pyproject must declare the isolated package name")

    def test_requirements_pin_the_sdk_exactly(self):
        path = MAPPING_PYTHON / "requirements-dev.txt"
        self.assertTrue(path.exists(), f"missing mapping pin file: {path}")
        entries = [
            line.strip() for line in read_text(path).splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(entries, "requirements-dev.txt must not be empty")
        for entry in entries:
            self.assertIn(
                entry, ALLOWED_REQUIREMENTS,
                f"unexpected mapping dependency: {entry}")
        self.assertEqual(
            entries.count(EXPECTED_SDK_PIN), 1,
            "requirements-dev.txt must pin google-adk==2.13.0 exactly once")

    def test_mapping_package_skeleton_exists(self):
        package = MAPPING_PYTHON / "src/boundrelay_m2_adk"
        for name in MAPPING_MODULES:
            self.assertTrue((package / name).is_file(),
                            f"missing mapping module: {name}")

    def test_pinned_sdk_imports_in_this_venv(self):
        self.assertEqual(
            metadata.version("google-adk"), "2.13.0",
            "the repo venv must carry the exactly-pinned google-adk")
        import google.adk  # allowed here: this file is the isolation allowlist
        self.assertTrue(google.adk.__name__ == "google.adk")


class P5bParityKeyContractTests(unittest.TestCase):
    def test_five_parity_case_keys_enumerated(self):
        path = ROOT / "fixtures/goprojections/support-handoff/scenario.json"
        self.assertTrue(path.exists(), f"missing scenario projection: {path}")
        scenario = json.loads(read_text(path))
        keys = tuple(case["id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 5, "the canonical M2 set is five cases")
        self.assertEqual(keys, PARITY_CASE_KEYS,
                         "parity case keys drifted from the canonical set")

    def test_every_parity_case_has_a_golden_projection(self):
        for key in PARITY_CASE_KEYS:
            path = ROOT / f"fixtures/goldens/support-handoff/{key}.json"
            self.assertTrue(path.exists(), f"missing golden: {path}")
            golden = json.loads(read_text(path))
            self.assertEqual(golden.get("case_key"), key,
                             f"golden case_key drift for {key}")
            self.assertIn("result_projection", golden,
                          f"golden {key} carries no result_projection")
            self.assertIn("attribution", golden["result_projection"],
                          f"golden {key} projection carries no attribution")


if __name__ == "__main__":
    unittest.main()
