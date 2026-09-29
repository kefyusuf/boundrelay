from io import StringIO
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from boundrelay_m1.cli import main, parse_cli_options


class CliTests(unittest.TestCase):
    def test_parse_requires_exact_options_and_rejects_duplicate_unknown(self):
        options=parse_cli_options(["--mode","direct","--case","direct-order-status","--trace","/tmp/t.jsonl"])
        self.assertEqual((options.mode,options.case_id,options.trace_path),("direct","direct-order-status","/tmp/t.jsonl"))
        with self.assertRaisesRegex(ValueError,"Duplicate option --mode"):
            parse_cli_options(["--mode","direct","--mode","agent","--case","x","--trace","y"])
        with self.assertRaisesRegex(ValueError,"Unexpected argument --other"):
            parse_cli_options(["--mode","direct","--case","x","--trace","y","--other","z"])

    def test_main_prints_exactly_one_json_line(self):
        with tempfile.TemporaryDirectory() as d:
            stdout=StringIO(); stderr=StringIO()
            code=main(["--mode","direct","--case","direct-order-status","--trace",str(Path(d)/"trace.jsonl")],stdout=stdout,stderr=stderr)
            self.assertEqual(code,0); self.assertEqual(stderr.getvalue(),"")
            self.assertEqual(len([x for x in stdout.getvalue().splitlines() if x]),1)
            self.assertIn('"status":"SUCCEEDED"',stdout.getvalue())

    def test_python_module_entrypoint_runs_direct_case(self):
        with tempfile.TemporaryDirectory() as d:
            env=os.environ.copy()
            process=subprocess.run(
                [sys.executable,"-m","boundrelay_m1","--mode","direct","--case","direct-order-status","--trace",str(Path(d)/"trace.jsonl")],
                text=True,capture_output=True,check=False,env=env,
            )
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertEqual(len([x for x in process.stdout.splitlines() if x]),1)
            self.assertIn('"status":"SUCCEEDED"',process.stdout)

    def test_main_maps_mode_mismatch_to_configuration_error(self):
        stdout=StringIO(); stderr=StringIO()
        code=main(["--mode","direct","--case","agent-delayed-shipment","--trace","/tmp/x.jsonl"],stdout=stdout,stderr=stderr)
        self.assertEqual(code,2); self.assertEqual(stdout.getvalue(),""); self.assertIn("mode",stderr.getvalue())
