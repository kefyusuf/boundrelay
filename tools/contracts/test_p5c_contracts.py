"""P5c contracts: @mastra/core dependency isolation, the mapping manifest,
and the six canonical M3 parity case keys.

Isolation: the pinned Mastra workflow-engine distribution ('@mastra/core',
bare root 'mastra') and the mapping package names must not appear in any
file under lessons/, contracts/, tools/, scripts/, or go/ outside the
precise allowlist below (this proving test). Two probes, both
fail-closed:
  1. a case-insensitive substring scan for the distinctive distribution
     and mapping-package tokens (mirrors the P5a/P5b/M8 scans; the bare
     import roots 'mastra' and '@mastra/core' both contain 'mastra', so
     the substring probe also covers the import names); and
  2. an import scan: no module under the scan roots may execute an
     import of the bare SDK roots (python-style 'import mastra' /
     'from mastra ...', TS-style imports from 'mastra' or
     '@mastra/core', or a dynamic import of either) - defense in depth
     against a token spelled to evade the substring scan.

Manifest: mappings/mastra-m3/typescript/package.json must name the
mapping package, and its dependencies must pin @mastra/core==1.82.0
exactly with no other runtime dependency (the framework's own transitive
tree, including its zod peer, rides on the lockfile).

Parity keys: the six canonical order-brief cases are enumerated and each
has an M3 golden projection whose result_projection is the parity target.
"""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("lessons", "contracts", "tools", "scripts", "go")
# Case-insensitive: the scoped distribution spelling, the bare root, and
# the mapping package names. The bare import roots ('mastra',
# '@mastra/core') are substrings of 'mastra', so the substring probe
# covers them; the import scan below adds defense in depth.
ISOLATION_TOKENS = (
    "@mastra/core", "mastra",
    "boundrelay_m3_mastra", "boundrelay-m3-mastra",
)
IMPORT_SCAN_PATTERN = re.compile(
    r"(?m)^\s*(?:import|from)\s+mastra\b"          # python-style
    r"|^\s*import\s+[^;\n]*\bfrom\s+['\"]@?mastra"  # TS named/default
    r"|^\s*import\s+['\"]@?mastra"                  # TS side-effect
    r"|import\s*\(\s*['\"]@?mastra")                # dynamic
ISOLATION_ALLOWLIST = (
    "tools/contracts/test_p5c_contracts.py",
)
MAPPING_TYPESCRIPT = ROOT / "mappings/mastra-m3/typescript"
EXPECTED_PACKAGE_NAME = "@boundrelay/mapping-mastra-m3"
EXPECTED_SDK_PIN = "1.82.0"
EXPECTED_SDK_DEPENDENCY = {"@mastra/core": "1.82.0"}
PARITY_CASE_KEYS = (
    "sequential-complete",
    "parallel-complete",
    "parallel-out-of-order",
    "parallel-partial-failure",
    "parallel-all-failed",
    "parallel-invalid-output",
)
MAPPING_MODULES = (
    "fixtures.ts", "results.ts", "attribution.ts",
    "mapping.ts", "naive.ts", "cli.ts",
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


class P5cIsolationContractTests(unittest.TestCase):
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
            "mastra/mapping references outside mappings/mastra-m3/ "
            "(and outside the precise allowlist) break P5c isolation")

    def test_no_bare_sdk_imports_outside_the_mapping(self):
        offenders = []
        for path in iter_scan_files():
            key = path.relative_to(ROOT).as_posix()
            if is_allowlisted(key):
                continue
            if path.suffix not in (".py", ".ts", ".tsx", ".mjs", ".js"):
                continue
            if IMPORT_SCAN_PATTERN.search(read_text(path)):
                offenders.append(key)
        self.assertEqual(
            offenders, [],
            "the mastra SDK modules must not be imported outside "
            "mappings/mastra-m3/ (and outside the precise allowlist)")


class P5cManifestContractTests(unittest.TestCase):
    def test_package_json_names_the_mapping_package(self):
        path = MAPPING_TYPESCRIPT / "package.json"
        self.assertTrue(path.exists(), f"missing mapping manifest: {path}")
        manifest = json.loads(read_text(path))
        self.assertEqual(
            manifest.get("name"), EXPECTED_PACKAGE_NAME,
            "mapping package.json must declare the isolated package name")

    def test_dependencies_pin_the_sdk_exactly(self):
        manifest = json.loads(read_text(MAPPING_TYPESCRIPT / "package.json"))
        dependencies = manifest.get("dependencies")
        self.assertEqual(
            dependencies, EXPECTED_SDK_DEPENDENCY,
            "dependencies must pin @mastra/core==1.82.0 exactly and carry "
            "no other runtime dependency")
        lock = json.loads(read_text(MAPPING_TYPESCRIPT / "package-lock.json"))
        locked = lock.get("packages", {}).get("node_modules/@mastra/core", {})
        self.assertEqual(
            locked.get("version"), EXPECTED_SDK_PIN,
            "the committed lockfile must resolve @mastra/core to 1.82.0")

    def test_mapping_package_skeleton_exists(self):
        package = MAPPING_TYPESCRIPT / "src"
        for name in MAPPING_MODULES:
            self.assertTrue((package / name).is_file(),
                            f"missing mapping module: {name}")

    def test_pinned_sdk_is_installed_and_importable_in_this_checkout(self):
        installed = json.loads(read_text(
            MAPPING_TYPESCRIPT / "node_modules/@mastra/core/package.json"))
        self.assertEqual(
            installed.get("version"), EXPECTED_SDK_PIN,
            "the mapping checkout must carry the exactly-pinned @mastra/core")
        probe = (
            "import('@mastra/core/workflows')"
            ".then(m=>{if(typeof m.createWorkflow!=='function')"
            "{console.error('bad export');process.exit(1);}})"
            ".catch(e=>{console.error(e&&e.message);process.exit(1);})")
        import subprocess
        completed = subprocess.run(
            ["node", "-e", probe], cwd=MAPPING_TYPESCRIPT,
            capture_output=True, text=True, timeout=120)
        self.assertEqual(
            completed.returncode, 0,
            f"@mastra/core must import from the mapping checkout: "
            f"{completed.stderr.strip()}")


class P5cParityKeyContractTests(unittest.TestCase):
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
