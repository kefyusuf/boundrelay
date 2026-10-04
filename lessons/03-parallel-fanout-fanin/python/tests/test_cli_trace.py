import unittest
from boundrelay_m3.cli import parse_cli_options,run_cli
class CliTests(unittest.TestCase):
    def test_strict_cli_rejects_invalid_arguments(self):
        base=['--mode','parallel','--case','parallel-complete','--trace','trace.jsonl']
        self.assertEqual(parse_cli_options(base)['mode'],'parallel')
        for args in [[],base[2:],base+['--case','other'],base+['--unknown','x'],base+['positional'],['--mode','other']+base[2:]]:
            with self.assertRaises(ValueError):parse_cli_options(args)
    def test_tooling_error_has_exit_two_and_no_result(self):
        stdout=[];stderr=[]
        code=run_cli(['--mode','sequential','--case','parallel-complete','--trace','unused.jsonl'],stdout.append,stderr.append)
        self.assertEqual(code,2);self.assertEqual(stdout,[]);self.assertTrue(stderr)
