import unittest
from tools.parity import verify_m0, verify_m1
from scripts import verify_m0 as gate0, verify_m1 as gate1


class CommandPortability(unittest.TestCase):
    def test_lower_gates_resolve_npm_on_current_platform(self):
        for gate in (gate0, gate1):
            gate.run(['npm','--version'])
        for verifier in (verify_m0, verify_m1):
            self.assertTrue(verifier._runtime_version(['npm','--version']))
