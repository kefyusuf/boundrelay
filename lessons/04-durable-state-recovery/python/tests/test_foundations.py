import unittest
from boundrelay_m4.paths import ROOT
class FoundationsTests(unittest.TestCase):
    def test_repository_paths_resolve_real_fixtures(self):
        self.assertTrue((ROOT/'fixtures/scenarios/order-brief-recovery.yaml').exists())
    def test_m4_closed_contracts_are_present(self):
        self.assertTrue((ROOT/'contracts/state/order-brief-run-state.schema.json').exists())
        self.assertTrue((ROOT/'contracts/results/order-brief-recovery-result.schema.json').exists())
        self.assertTrue((ROOT/'contracts/events/run-event.schema.json').exists())
