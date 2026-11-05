"""M8 contracts: langgraph dependency isolation, the mapping manifest,
and the six canonical M3 parity case keys.

Isolation: the token 'langgraph' (and the mapping package names) must not
appear in any file under lessons/, contracts/, tools/, scripts/, or go/
outside the precise allowlist below (this proving test plus the Task 4
gate files that reference the mapping in gate logic). The scan is
fail-closed: any occurrence outside the allowlist fails.

Manifest: mappings/langgraph-m3/python/pyproject.toml must name the
package boundrelay-m3-langgraph, and requirements-dev.txt must pin
langgraph==1.2.20 exactly with no other framework dependency (only the
shared PyYAML/jsonschema dev pins may accompany it).

Parity keys: the six canonical order-brief cases are enumerated and each
has an M3 golden projection whose result_projection is the parity target.
"""
from pathlib import Path
import json
import tomllib
import unittest
from importlib import metadata

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("lessons", "contracts", "tools", "scripts", "go")
# Case-insensitive: 'langgraph' also covers the package/import spellings.
ISOLATION_TOKENS = ("langgraph", "boundrelay_m3_langgraph", "boundrelay-m3-langgraph")
ISOLATION_ALLOWLIST = (
    "tools/contracts/test_m8_contracts.py",
    "tools/parity/verify_m8.py",
    "tools/parity/test_m8_verification_safety.py",
    "scripts/verify_m8.py",
)
MAPPING_PYTHON = ROOT / "mappings/langgraph-m3/python"
EXPECTED_PACKAGE_NAME = "boundrelay-m3-langgraph"
EXPECTED_LANGGRAPH_PIN = "langgraph==1.2.20"
ALLOWED_REQUIREMENTS = frozenset({
    "langgraph==1.2.20",
    "PyYAML==6.0.3",
    "jsonschema[format]==4.26.0",
})
PARITY_CASE_KEYS = (
    "sequential-complete",
    "parallel-complete",
    "parallel-out-of-order",
    "parallel-partial-failure",
    "parallel-all-failed",
    "parallel-invalid-output",
)
MAPPING_MODULES = (
    "__init__.py", "fixtures.py", "results.py", "attribution.py",
    "graph.py", "naive.py", "cli.py",
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


class M8IsolationContractTests(unittest.TestCase):
    def test_no_langgraph_references_outside_the_mapping(self):
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
            "langgraph/mapping references outside mappings/langgraph-m3/ "
            "(and outside the precise allowlist) break M8 isolation")


class M8ManifestContractTests(unittest.TestCase):
    def test_pyproject_names_the_mapping_package(self):
        path = MAPPING_PYTHON / "pyproject.toml"
        self.assertTrue(path.exists(), f"missing mapping manifest: {path}")
        with path.open("rb") as handle:
            manifest = tomllib.load(handle)
        self.assertEqual(
            manifest.get("project", {}).get("name"), EXPECTED_PACKAGE_NAME,
            "mapping pyproject must declare the isolated package name")

    def test_requirements_pin_langgraph_exactly(self):
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
            entries.count(EXPECTED_LANGGRAPH_PIN), 1,
            "requirements-dev.txt must pin langgraph==1.2.20 exactly once")

    def test_mapping_package_skeleton_exists(self):
        package = MAPPING_PYTHON / "src/boundrelay_m3_langgraph"
        for name in MAPPING_MODULES:
            self.assertTrue((package / name).is_file(),
                            f"missing mapping module: {name}")

    def test_pinned_langgraph_imports_in_this_venv(self):
        self.assertEqual(
            metadata.version("langgraph"), "1.2.20",
            "the repo venv must carry the exactly-pinned langgraph")
        import langgraph  # allowed here: this file is the isolation allowlist
        self.assertTrue(langgraph.__name__ == "langgraph")


class M8ParityKeyContractTests(unittest.TestCase):
    def test_six_parity_case_keys_enumerated(self):
        path = ROOT / "fixtures/goprojections/order-brief/scenario.json"
        self.assertTrue(path.exists(), f"missing scenario projection: {path}")
        scenario = json.loads(read_text(path))
        keys = tuple(case["case_id"] for case in scenario["cases"])
        self.assertEqual(len(keys), 6, "the canonical M3 set is six cases")
        self.assertEqual(keys, PARITY_CASE_KEYS,
                         "parity case keys drifted from the canonical set")

    def test_every_parity_case_has_a_golden_projection(self):
        for key in PARITY_CASE_KEYS:
            path = ROOT / f"fixtures/goldens/order-brief/{key}.json"
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
