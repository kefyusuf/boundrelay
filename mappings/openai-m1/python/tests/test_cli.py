"""CLI contract: one JSON result line, exit 0 domain / 2 tooling."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from boundrelay_m1_openai import cli


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trace = str(Path(self.tmp.name) / "trace.jsonl")

    def _run(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.run_cli(list(args), stdout=stdout.write, stderr=stderr.write)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_success_case_prints_one_result_line(self):
        code, out, err = self._run("--case", "agent-delayed-shipment",
                                   "--trace", self.trace)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        lines = out.splitlines()
        self.assertEqual(len(lines), 1)
        result = json.loads(lines[0])
        self.assertEqual(result["case_id"], "agent-delayed-shipment")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertTrue(Path(self.trace).is_file())

    def test_failure_case_is_a_domain_result(self):
        code, out, _ = self._run("--case", "agent-tool-failure",
                                 "--trace", self.trace)
        self.assertEqual(code, 0)
        result = json.loads(out.splitlines()[0])
        self.assertEqual(result["failure_code"], "TOOL_EXECUTION_FAILED")

    def test_unknown_case_exits_two(self):
        code, out, err = self._run("--case", "not-a-case",
                                   "--trace", self.trace)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("ValueError", err)

    def test_missing_trace_exits_two(self):
        code, out, _ = self._run("--case", "agent-delayed-shipment")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_odd_arguments_exit_two(self):
        code, _, _ = self._run("--case")
        self.assertEqual(code, 2)

    def test_duplicate_options_exit_two(self):
        code, _, _ = self._run("--case", "agent-delayed-shipment",
                               "--case", "agent-step-budget",
                               "--trace", self.trace)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
