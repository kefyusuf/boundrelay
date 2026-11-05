"""CLI exit codes: 0 for domain results (including PARTIAL/FAILED), 2 for
tooling errors (unknown case/options, naive-mode default propagation)."""
import json
import tempfile
import unittest
from pathlib import Path

from boundrelay_m3_langgraph import cli, fixtures


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def out(self, name):
        return str(self.dir / name)

    def run_cli(self, args, stdout=None, stderr=None):
        lines, errors = [], []
        code = cli.run_cli(
            args,
            stdout=lines.append if stdout is None else stdout,
            stderr=errors.append if stderr is None else stderr)
        return code, "".join(lines), "".join(errors)

    def test_corrected_mode_emits_one_json_line_and_exits_zero(self):
        for key in fixtures.PARITY_CASE_KEYS:
            with self.subTest(case=key):
                trace = self.out(f"{key}.jsonl")
                code, out, err = self.run_cli(
                    ["--case", key, "--trace", trace])
                self.assertEqual(code, 0, err)
                self.assertEqual(err, "")
                payload = json.loads(out)
                self.assertEqual(payload["case_id"], key)
                self.assertEqual(len(out.strip().splitlines()), 1)
                self.assertTrue(Path(trace).stat().st_size > 0)

    def test_explicit_corrected_mode_matches_default(self):
        trace = self.out("explicit.jsonl")
        code, out, _ = self.run_cli(
            ["--case", "parallel-complete", "--mode", "corrected",
             "--trace", trace])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "SUCCEEDED")

    def test_tooling_errors_exit_two(self):
        cases = [
            ["--case", "no-such-case", "--trace", self.out("t.jsonl")],
            ["--case", "parallel-complete"],
            ["--trace", self.out("t.jsonl")],
            [],
            ["--case", "parallel-complete", "--trace", self.out("t.jsonl"),
             "--extra", "x"],
            ["--case", "parallel-complete", "--case", "parallel-complete",
             "--trace", self.out("t.jsonl")],
            ["--case", "parallel-complete", "--trace", self.out("t.jsonl"),
             "positional"],
            ["--case", "parallel-complete", "--trace", self.out("t.jsonl"),
             "--mode", "bogus"],
        ]
        for args in cases:
            with self.subTest(args=args):
                code, out, err = self.run_cli(args)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertTrue(err.strip(), "stderr must explain the error")

    def test_naive_mode_divergence(self):
        trace = self.out("naive.jsonl")
        code, out, _ = self.run_cli(
            ["--case", "parallel-complete", "--mode", "naive",
             "--trace", trace])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["peak_concurrency"], 3)

    def test_naive_mode_declared_failure_exits_two(self):
        trace = self.out("naive-failed.jsonl")
        code, out, err = self.run_cli(
            ["--case", "parallel-partial-failure", "--mode", "naive",
             "--trace", trace])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("Declared worker failure", err)
        self.assertTrue(Path(trace).stat().st_size > 0,
                        "the flushed stream prefix remains inspectable")


if __name__ == "__main__":
    unittest.main()
