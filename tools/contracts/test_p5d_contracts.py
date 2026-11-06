"""P5d contracts: Eino dependency isolation, the mapping manifest, and the
six canonical M3 parity case keys.

Isolation: the pinned Eino distribution ('github.com/cloudwego/eino', bare
root 'eino') and the mapping package names must not appear in any file
under lessons/, contracts/, tools/, scripts/, or go/ outside the precise
allowlist below (this proving test). Three probes, all fail-closed:
  1. a case-insensitive substring scan for the distinctive distribution
     and mapping-package tokens (mirrors the M8/P5a/P5b/P5c scans; the
     bare import root 'eino' is a substring of 'cloudwego/eino', so the
     substring probe also covers the import paths);
  2. an import scan: no Go file under the scan roots may import the Eino
     packages (defense in depth against a token spelled to evade the
     substring scan); and
  3. a Python import scan mirroring the earlier mappings (python-style
     'import eino' / 'from eino ...'), so a foreign-language file cannot
     smuggle the distribution either.

Manifest: mappings/eino-m3/go/go.mod must name the module
boundrelay-m3-eino, require github.com/cloudwego/eino at the pinned
version exactly once, and the mapping skeleton
(internal/{fixtures,results,attribution,mapping,cli} + cmd/main.go) must
exist. The pinned framework must resolve in this checkout (module cache
present, and `go build ./...` compiles the mapping offline).

Parity keys: the six canonical order-brief cases are enumerated and each
has an M3 golden projection whose result_projection is the parity target.
"""
from pathlib import Path
import json
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("lessons", "contracts", "tools", "scripts", "go")
# Case-insensitive: the distribution path, the bare root, and the mapping
# package names. 'eino' also covers the import spellings.
ISOLATION_TOKENS = (
    "github.com/cloudwego/eino", "cloudwego", "eino",
    "boundrelay_m3_eino", "boundrelay-m3-eino",
)
GO_IMPORT_SCAN_PATTERN = re.compile(
    r'^\s*(?:import|\})?\s*[_a-zA-Z0-9]*\s*"github\.com/cloudwego/eino',
    re.MULTILINE,
)
PY_IMPORT_SCAN_PATTERN = re.compile(
    r"(?m)^\s*(?:import|from)\s+eino\b"
    r"|import\s*\(\s*['\"]eino"
)
ISOLATION_ALLOWLIST = (
    "tools/contracts/test_p5d_contracts.py",
)
MAPPING_GO = ROOT / "mappings/eino-m3/go"
EXPECTED_MODULE_NAME = "boundrelay-m3-eino"
EXPECTED_SDK_REQUIRE = "github.com/cloudwego/eino v0.9.22"
PARITY_CASE_KEYS = (
    "sequential-complete",
    "parallel-complete",
    "parallel-out-of-order",
    "parallel-partial-failure",
    "parallel-all-failed",
    "parallel-invalid-output",
)
MAPPING_MODULES = (
    "internal/fixtures/fixtures.go", "internal/results/results.go",
    "internal/attribution/attribution.go", "internal/mapping/mapping.go",
    "internal/mapping/executor.go", "internal/mapping/naive.go",
    "internal/cli/cli.go", "cmd/main.go",
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


def is_binary(path):
    """Binary artifacts (checked-in toolchain binaries under lessons'
    node_modules) are out of scope for a substring scan: their bytes
    coincidentally contain short tokens like 'eino'. A NUL byte in the
    first 8 KiB marks a binary; every text file is still scanned."""
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError as error:
        raise AssertionError(f"Unreadable scan target: {path}") from error


def iter_scan_files():
    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            raise AssertionError(f"Missing scan root: {base}")
        for path in sorted(base.rglob("*")):
            if path.is_file() and not is_binary(path):
                yield path


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise AssertionError(f"Unreadable scan target: {path}") from error


class P5dIsolationContractTests(unittest.TestCase):
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
            "eino/mapping references outside mappings/eino-m3/ "
            "(and outside the precise allowlist) break P5d isolation")

    def test_no_go_sdk_imports_outside_the_mapping(self):
        offenders = []
        for path in iter_scan_files():
            key = path.relative_to(ROOT).as_posix()
            if is_allowlisted(key):
                continue
            if path.suffix != ".go":
                continue
            if GO_IMPORT_SCAN_PATTERN.search(read_text(path)):
                offenders.append(key)
        self.assertEqual(
            offenders, [],
            "the eino SDK packages must not be imported outside "
            "mappings/eino-m3/ (and outside the precise allowlist)")

    def test_no_python_style_sdk_imports_outside_the_mapping(self):
        offenders = []
        for path in iter_scan_files():
            key = path.relative_to(ROOT).as_posix()
            if is_allowlisted(key):
                continue
            if path.suffix != ".py":
                continue
            if PY_IMPORT_SCAN_PATTERN.search(read_text(path)):
                offenders.append(key)
        self.assertEqual(
            offenders, [],
            "no python-style eino import may appear outside "
            "mappings/eino-m3/ (and outside the precise allowlist)")


class P5dManifestContractTests(unittest.TestCase):
    def read_go_mod(self):
        path = MAPPING_GO / "go.mod"
        self.assertTrue(path.exists(), f"missing mapping manifest: {path}")
        return read_text(path)

    def test_go_mod_names_the_mapping_module(self):
        module = None
        for line in self.read_go_mod().splitlines():
            if line.startswith("module "):
                module = line[len("module "):].strip()
                break
        self.assertEqual(
            module, EXPECTED_MODULE_NAME,
            "mapping go.mod must declare the isolated module name")

    def test_go_mod_pins_the_sdk_exactly(self):
        content = self.read_go_mod()
        # Matches both the single-line ('require <path> <version>') and the
        # block ('<path> <version>' inside require (...)) forms.
        pattern = re.compile(
            r"(?m)^\s*(?:require\s+)?github\.com/cloudwego/eino\s+v0\.9\.22\s*(?://.*)?$")
        requires = [match.strip() for match in pattern.findall(content)]
        requires = [re.sub(r"^(require\s+)?", "", require) for require in requires]
        self.assertEqual(
            requires, [EXPECTED_SDK_REQUIRE],
            "go.mod must require github.com/cloudwego/eino v0.9.22 exactly "
            "once and carry no other eino require")

    def test_go_sum_committed(self):
        go_sum = MAPPING_GO / "go.sum"
        self.assertTrue(go_sum.exists(), "the mapping must commit go.sum")
        self.assertIn("github.com/cloudwego/eino v0.9.22", read_text(go_sum),
                      "go.sum must resolve the pinned eino version")

    def test_mapping_module_skeleton_exists(self):
        for name in MAPPING_MODULES:
            self.assertTrue((MAPPING_GO / name).is_file(),
                            f"missing mapping module: {name}")

    def test_pinned_sdk_resolves_and_the_mapping_compiles_offline(self):
        module_cache = subprocess.run(
            ["go", "env", "GOMODCACHE"], capture_output=True, text=True,
            timeout=60)
        self.assertEqual(module_cache.returncode, 0,
                         f"go env failed: {module_cache.stderr}")
        pinned = (Path(module_cache.stdout.strip()) /
                  "github.com/cloudwego/eino@v0.9.22")
        self.assertTrue(pinned.is_dir(),
                        "the pinned eino distribution must be in the module "
                        "cache of this checkout")
        completed = subprocess.run(
            ["go", "build", "./..."], cwd=MAPPING_GO,
            capture_output=True, text=True, timeout=600)
        self.assertEqual(
            completed.returncode, 0,
            f"the mapping must compile against the pinned eino: "
            f"{completed.stdout}\n{completed.stderr}")


class P5dParityKeyContractTests(unittest.TestCase):
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
