"""M8 verifier-safety suite: mutations that must fail before M8 evidence is
published — isolation breaches, canonical-tree mutations, mapping parity
drift, tampered reports, moved HEAD, dirty trees, stale evidence — mirroring
the M7 suite. All heavy boundaries are faked; the suite stays fast and
scripts/verify_m8.py performs the real runs. Naive-mode divergence is a
positive control here: it is expected, never a certification defect.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from itertools import count
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.parity import verify_m8 as gate

LANGGRAPH_PIN = "1.2.20"


def fake_tree(base):
    """A disposable minimal tree with the five isolation scan roots and a
    couple of canonical artifact files."""
    for root in gate.ISOLATION_SCAN_ROOTS:
        (base / root).mkdir(parents=True, exist_ok=True)
    (base / "lessons" / "note.txt").write_text("benign lesson text",
                                               encoding="utf-8")
    golden = base / "fixtures" / "goldens" / "x.json"
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text("{}", encoding="utf-8")
    return base


def contracts_report():
    ids = list(gate.M8_CONTRACT_PROBE_IDS)
    return {"successful": True, "tests_run": len(ids), "discovered": list(ids),
            "passed": list(ids), "failed": [], "skipped": []}


def mapping_report():
    required = list(gate.M8_MAPPING_PROBE_IDS)
    filler = [f"mapping.filler_{index}" for index in
              range(gate.TOTAL_MAPPING_TESTS - len(required))]
    ids = filler + required
    return {"successful": True, "tests_run": gate.TOTAL_MAPPING_TESTS,
            "discovered": ids, "passed": list(ids), "failed": [],
            "skipped": []}


def combined_report():
    contracts = contracts_report()
    mapping = mapping_report()
    return {"successful": True,
            "tests_run": contracts["tests_run"] + mapping["tests_run"],
            "discovered": contracts["discovered"] + mapping["discovered"],
            "passed": contracts["passed"] + mapping["passed"],
            "failed": [], "skipped": []}
class M8VerificationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.counter = count()

    def test_validate_isolation_accepts_honest_trees(self):
        with patch.object(gate, "ROOT", fake_tree(self.root / "honest")):
            proof = gate.validate_isolation()
        self.assertEqual(proof["status"], "matched")

    def test_isolation_breach_blocks(self):
        breaches = {
            "import": "import langgraph\n",
            "package": "from boundrelay_m3_langgraph import fixtures\n",
            "name": "boundrelay-m3-langgraph pin\n",
        }
        for name, text in breaches.items():
            with self.subTest(name=name):
                base = fake_tree(self.root / f"breach-{next(self.counter)}")
                (base / "scripts" / "sneaky.py").write_text(text,
                                                            encoding="utf-8")
                with patch.object(gate, "ROOT", base):
                    with self.assertRaises(RuntimeError) as caught:
                        gate.validate_isolation()
                self.assertIn("scripts/sneaky.py", str(caught.exception))

    def test_isolation_allowlist_and_missing_root_fail_closed(self):
        base = fake_tree(self.root / "allowlisted")
        allowlisted = base / "tools" / "parity" / "verify_m8.py"
        allowlisted.parent.mkdir(parents=True, exist_ok=True)
        allowlisted.write_text("the langgraph pin lives here\n",
                               encoding="utf-8")
        with patch.object(gate, "ROOT", base):
            self.assertEqual(gate.validate_isolation()["status"], "matched")
        with patch.object(gate, "ROOT", self.root / "absent-roots"):
            with self.assertRaises(RuntimeError):
                gate.validate_isolation()

    def test_canonical_tree_mutation_blocks(self):
        base = fake_tree(self.root / "canonical")
        with patch.object(gate, "ROOT", base):
            snapshot = gate.canonical_tree_snapshot()
            self.assertTrue(snapshot, "snapshot must cover canonical files")
            proof = gate.validate_canonical_tree(snapshot)
            self.assertEqual(proof["status"], "unchanged")
            golden = base / "fixtures" / "goldens" / "x.json"
            golden.write_text('{"tampered": true}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                gate.validate_canonical_tree(snapshot)
            golden.write_text("{}", encoding="utf-8")
            (base / "lessons" / "injected.txt").write_text("new",
                                                           encoding="utf-8")
            with self.assertRaises(RuntimeError):
                gate.validate_canonical_tree(snapshot)
            (base / "lessons" / "injected.txt").unlink()
            (base / "lessons" / "note.txt").unlink()
            with self.assertRaises(RuntimeError):
                gate.validate_canonical_tree(snapshot)

    def _mapping_fixture_copy(self):
        """A disposable copy of the mapping's fixture inputs (projections +
        goldens) so parity drift can be fabricated without dirtying the
        worktree. Returns the two replacement directory paths."""
        projections = self.root / f"projections-{next(self.counter)}"
        goldens = self.root / f"goldens-{next(self.counter)}"
        shutil.copytree(ROOT / "fixtures/goprojections/order-brief",
                        projections)
        shutil.copytree(ROOT / "fixtures/goldens/order-brief", goldens)
        return projections, goldens

    def _run_one_parity_probe(self, projections, goldens):
        """Run the mapping suite's six-case parity probe in-process against
        replacement fixture directories (the mapping's own compare)."""
        sys.path.insert(0, str(gate.MAPPING_SRC))
        sys.path.insert(0, str(gate.MAPPING_TESTS))
        try:
            from boundrelay_m3_langgraph import fixtures
            import unittest as unit
            suite = unit.TestLoader().loadTestsFromName(
                "test_graph_parity.SixCaseParityTests"
                ".test_business_projection_equals_golden_for_all_six_cases")
            with patch.object(fixtures, "PROJECTION_DIR", projections), \
                 patch.object(fixtures, "GOLDEN_DIR", goldens):
                result = unit.TextTestRunner(stream=io.StringIO(),
                                             verbosity=0).run(suite)
        finally:
            sys.path.remove(str(gate.MAPPING_SRC))
            sys.path.remove(str(gate.MAPPING_TESTS))
        return result

    def test_parity_divergence_blocks(self):
        projections, goldens = self._mapping_fixture_copy()
        honest = self._run_one_parity_probe(projections, goldens)
        self.assertTrue(honest.wasSuccessful(),
                        "the honest fixture copy must pass the parity probe")
        drifted = goldens / "parallel-complete.json"
        document = json.loads(drifted.read_text(encoding="utf-8"))
        document["result_projection"]["status"] = "FAILED"
        drifted.write_text(json.dumps(document), encoding="utf-8")
        diverged = self._run_one_parity_probe(projections, goldens)
        self.assertFalse(diverged.wasSuccessful(),
                         "a diverged golden must fail the mapping's compare")
        failed_ids = [test.id() for test, _ in diverged.failures]
        parity_probe = ("test_graph_parity.SixCaseParityTests"
                        ".test_business_projection_equals_golden_for_all_six_cases")
        self.assertTrue(all(name.startswith(parity_probe) for name in failed_ids),
                        failed_ids)
        self.assertEqual(len(failed_ids), 1,
                         "exactly the drifted case's subTest may refuse")
        self.assertIn("parallel-complete", failed_ids[0])
        report = mapping_report()
        report["failed"] = list(failed_ids)
        report["passed"] = [i for i in report["passed"] if i != parity_probe]
        with self.assertRaises(ValueError):
            gate.validate_probe_reports(report, required=gate.M8_MAPPING_PROBE_IDS,
                                        expected_tests=gate.TOTAL_MAPPING_TESTS)

    def test_naive_divergence_is_expected_not_a_defect(self):
        """Positive control: naive mode is the teaching artifact. Its
        results legitimately diverge from the goldens (uncapped peak, no
        taxonomy) and no naive-parity requirement exists in the gate."""
        sys.path.insert(0, str(gate.MAPPING_SRC))
        try:
            from boundrelay_m3_langgraph import fixtures, naive, results
            naive_result = naive.run_naive(
                "parallel-complete", str(self.root / "naive.jsonl"))
            golden = fixtures.load_golden("parallel-complete")
            projection = {key: value for key, value in naive_result.items()
                          if key not in ("run_id", "trace_path")}
            self.assertNotEqual(projection, golden,
                                "naive divergence is the expected behavior")
            self.assertNotEqual(naive_result["peak_concurrency"],
                                golden["peak_concurrency"])
            self.assertFalse(results.validate_result(naive_result))
        finally:
            sys.path.remove(str(gate.MAPPING_SRC))
        proof = gate.validate_probe_reports(
            mapping_report(), required=gate.M8_MAPPING_PROBE_IDS,
            expected_tests=gate.TOTAL_MAPPING_TESTS)
        self.assertIn(
            "test_naive_regression.NaiveDefaultPropagationTests"
            ".test_uncapped_dispatch_is_observed_not_normalized",
            proof["passed_probes"])

    def test_missing_probe_or_failed_suite_cannot_certify(self):
        contracts = gate.validate_probe_reports(
            contracts_report(), required=gate.M8_CONTRACT_PROBE_IDS,
            expected_tests=gate.TOTAL_CONTRACT_PROBES)
        self.assertEqual(contracts["passed_probes"],
                         sorted(gate.M8_CONTRACT_PROBE_IDS))
        mapping = gate.validate_probe_reports(
            mapping_report(), required=gate.M8_MAPPING_PROBE_IDS,
            expected_tests=gate.TOTAL_MAPPING_TESTS)
        self.assertEqual(mapping["tests"], gate.TOTAL_MAPPING_TESTS)
        combined = gate.validate_probe_reports(combined_report())
        self.assertEqual(combined["passed_probes"],
                         sorted(gate.REQUIRED_PROBE_IDS))
        contract = gate.M8_CONTRACT_PROBE_IDS[0]
        parity = gate.M8_MAPPING_PROBE_IDS[0]
        # (mutation, which suite it applies to) — every mutation must be
        # meaningful for its target report.
        mutations = [
            (lambda r: r.update(successful=False), "both"),
            (lambda r: r.update(tests_run=0), "both"),
            (lambda r: r.update(failed=[parity]), "both"),
            (lambda r: r.update(skipped=[contract]), "both"),
            (lambda r: r.update(discovered=r["discovered"][:-1]), "both"),
            (lambda r: r.update(passed=[i for i in r["passed"] if i != parity]),
             "mapping"),
            (lambda r: r.update(passed=[i for i in r["passed"] if i != contract]),
             "contracts"),
            (lambda r: r.update(
                discovered=["unittest.loader._FailedTest.test_x"]), "both"),
        ]
        builders = {
            "contracts": (contracts_report,
                          {"required": gate.M8_CONTRACT_PROBE_IDS,
                           "expected_tests": gate.TOTAL_CONTRACT_PROBES}),
            "mapping": (mapping_report,
                        {"required": gate.M8_MAPPING_PROBE_IDS,
                         "expected_tests": gate.TOTAL_MAPPING_TESTS}),
        }
        for mutate, applies in mutations:
            for name in ("contracts", "mapping") if applies == "both" else (applies,):
                builder, kwargs = builders[name]
                report = builder()
                mutate(report)
                with self.subTest(suite=name, mutation=mutate):
                    with self.assertRaises(ValueError):
                        gate.validate_probe_reports(report, **kwargs)

    def evidence(self, revision="start"):
        return {"schema_version": "1.0", "milestone": "m8",
                "status": "PASSED", "revision": revision,
                "command": "python scripts/verify_m8.py",
                "runtimes": {"python": "3.14", "langgraph": LANGGRAPH_PIN},
                "isolation": {"status": "matched"},
                "canonical_tree": {"files": 12, "status": "unchanged"},
                "contracts_probes": gate.validate_probe_reports(
                    contracts_report(), required=gate.M8_CONTRACT_PROBE_IDS,
                    expected_tests=gate.TOTAL_CONTRACT_PROBES),
                "mapping_suite": {
                    "totals": {"passed": gate.TOTAL_MAPPING_TESTS,
                               "failed": 0, "skipped": 0},
                    "probes": gate.validate_probe_reports(
                        mapping_report(), required=gate.M8_MAPPING_PROBE_IDS,
                        expected_tests=gate.TOTAL_MAPPING_TESTS)},
                "probe_reports": {"tests": 45,
                                  "passed_probes": sorted(gate.REQUIRED_PROBE_IDS)},
                "test_commands": ["python scripts/verify_m7.py",
                                  "unittest probe discovery (M8 contracts "
                                  "+ mapping suite)",
                                  "python -m unittest "
                                  "tools.parity.test_m8_verification_safety",
                                  "python -O -m unittest "
                                  "tools.parity.test_m8_verification_safety"]}

    def _publish_contexts(self, target, clean=True, lower=None, head="start",
                          isolation=None, canonical=None):
        return [patch.object(gate, "EVIDENCE_PATH", target),
                patch.object(gate, "validate_lower_evidence") if lower is None
                else patch.object(gate, "validate_lower_evidence",
                                  side_effect=RuntimeError(lower)),
                patch.object(gate, "assert_clean_worktree") if clean
                else patch.object(gate, "assert_clean_worktree",
                                  side_effect=RuntimeError("dirty")),
                patch.object(gate, "_revision", return_value=head),
                patch.object(gate, "validate_isolation") if isolation is None
                else patch.object(gate, "validate_isolation",
                                  side_effect=RuntimeError(isolation)),
                patch.object(gate, "validate_canonical_tree")
                if canonical is None
                else patch.object(gate, "validate_canonical_tree",
                                  side_effect=RuntimeError(canonical))]

    def attempt_publication(self, mutate=None, revision="start",
                            starting="start", clean=True, lower=None,
                            head=None, isolation=None, canonical=None,
                            expect=True):
        evidence = self.evidence(revision)
        if mutate is not None:
            mutate(evidence)
        target = self.root / f"publish-{next(self.counter)}.json"
        contexts = self._publish_contexts(target, clean=clean, lower=lower,
                                          head=head or starting,
                                          isolation=isolation,
                                          canonical=canonical)
        with contextlib.ExitStack() as stack:
            for context in contexts:
                stack.enter_context(context)
            if expect:
                gate.publish_evidence(evidence, starting)
            else:
                with self.assertRaises(RuntimeError):
                    gate.publish_evidence(evidence, starting)
        return target

    def test_tampered_reports_cannot_publish_passed_evidence(self):
        self.assertTrue(self.attempt_publication().exists())

        def refused(mutate=None, **options):
            target = self.attempt_publication(mutate, expect=False, **options)
            self.assertFalse(target.exists())

        refused(mutate=lambda e: e["mapping_suite"]["totals"].update(passed=37, failed=1))
        refused(mutate=lambda e: e["mapping_suite"]["totals"].update(skipped=1))
        refused(mutate=lambda e: e["mapping_suite"].pop("totals"))
        refused(mutate=lambda e: e["mapping_suite"].pop("probes"))
        refused(mutate=lambda e: e["mapping_suite"]["probes"].update(passed_probes=[]))
        refused(mutate=lambda e: e["contracts_probes"].update(tests=6))
        refused(mutate=lambda e: e.pop("contracts_probes"))
        refused(mutate=lambda e: e["probe_reports"].update(
            passed_probes=e["probe_reports"]["passed_probes"][:-1]))
        refused(mutate=lambda e: e.pop("probe_reports"))
        refused(mutate=lambda e: e["isolation"].update(status="breached"))
        refused(mutate=lambda e: e.pop("isolation"))
        refused(mutate=lambda e: e["canonical_tree"].update(status="mutated"))
        refused(mutate=lambda e: e.pop("canonical_tree"))
        refused(mutate=lambda e: e["runtimes"].update(langgraph="1.3.0"))
        refused(mutate=lambda e: e["runtimes"].pop("langgraph"))
        refused(mutate=lambda e: e.pop("runtimes"))
        refused(isolation="isolation breached during publication")
        refused(canonical="canonical tree mutated during publication")

    def test_publication_checks_survive_optimization(self):
        self.assertTrue(self.attempt_publication().exists())

        def refused(**options):
            self.attempt_publication(expect=False, **options)

        refused(head="changed")            # HEAD moved during verification
        refused(clean=False)               # dirty worktree
        refused(lower="wrong lower revision")  # stale/failed m7 evidence
        refused(starting="other", head="other")  # evidence identity mismatch
        refused(isolation="breach")        # isolation re-check blocks
        refused(canonical="drift")         # canonical re-check blocks

    def test_lower_evidence_must_be_m7_passed_on_revision(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            evidence = (Path(directory) / ".boundrelay/m7"
                        / "verification-evidence.json")
            evidence.parent.mkdir(parents=True)
            with patch.object(gate, "ROOT", Path(directory)):
                def attempt(document):
                    evidence.write_text(json.dumps(document), encoding="utf-8")
                    gate.validate_lower_evidence("start")
                attempt({"status": "PASSED", "revision": "start",
                         "milestone": "m7"})
                for mutate in (lambda d: d.update(status="FAILED"),
                               lambda d: d.update(revision="other"),
                               lambda d: d.update(milestone="m6")):
                    document = {"status": "PASSED", "revision": "start",
                                "milestone": "m7"}
                    mutate(document)
                    with self.assertRaises(RuntimeError):
                        attempt(document)
                evidence.unlink()
                with self.assertRaises(RuntimeError):
                    gate.validate_lower_evidence("start")

    def test_stale_output_removed_before_first_gate_command(self):
        from scripts import verify_m8 as authority
        output = self.root / "m8"
        output.mkdir()
        stale = output / "verification-evidence.json"
        stale.write_text("old")
        events = []

        def stop(*args, **kwargs):
            events.append("command")
            self.assertFalse(stale.exists(),
                             "stale evidence must be cleared first")
            raise RuntimeError("lower chain failed")

        with patch.object(gate, "OUTPUT_ROOT", output), \
             patch.object(authority.gate, "run_cli", side_effect=stop), \
             patch.object(gate, "assert_clean_worktree"), \
             patch.object(gate, "_revision", return_value="start"):
            with self.assertRaises(RuntimeError):
                authority.main()
        self.assertEqual(events, ["command"],
                         "no gate command may run before the clear")
        self.assertFalse(stale.exists())

    def test_stale_output_removed_for_dirty_preflight(self):
        from scripts import verify_m8 as authority
        output = self.root / "m8"
        output.mkdir()
        stale = output / "verification-evidence.json"
        stale.write_text('{"status": "PASSED"}')
        with patch.object(gate, "OUTPUT_ROOT", output), \
             patch.object(gate, "assert_clean_worktree",
                          side_effect=RuntimeError("dirty")):
            with self.assertRaises(RuntimeError):
                authority.main()
        self.assertFalse(stale.exists())

    def test_evidence_clear_rejects_symlink_redirect(self):
        for placement in ("leaf", "parent"):
            with self.subTest(placement=placement):
                external = self.root / placement / "outside" / "m8"
                external.mkdir(parents=True)
                marker = external / "important.txt"
                marker.write_text("preserve", encoding="utf-8")
                workspace = self.root / placement / "workspace"
                workspace.mkdir(parents=True)
                output = workspace / ".boundrelay" / "m8"
                if placement == "leaf":
                    output.parent.mkdir()
                    link, destination = output, external
                else:
                    link, destination = output.parent, external.parent
                try:
                    link.symlink_to(destination, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("Directory symlinks are unavailable")
                with patch.object(gate, "OUTPUT_ROOT", output):
                    with self.assertRaises(RuntimeError):
                        gate.clear_previous_evidence()
                self.assertTrue(marker.exists())

    def test_mapping_suite_collection_sets_and_restores_import_path(self):
        class ChildImportTest(unittest.TestCase):
            def runTest(self):
                code = ("import boundrelay_m3_langgraph as m; "
                        "print(m.__name__)")
                process = subprocess.run(
                    [sys.executable, "-c", code], cwd=ROOT,
                    capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(unittest.TestLoader, "discover",
                          return_value=unittest.TestSuite([ChildImportTest()])):
            report = gate.run_mapping_suite()
            self.assertTrue(report["successful"])
            self.assertNotIn(str(gate.MAPPING_SRC),
                             os.environ.get("PYTHONPATH", ""))
            self.assertNotIn(str(gate.MAPPING_SRC), sys.path)


if __name__ == "__main__":
    unittest.main()
