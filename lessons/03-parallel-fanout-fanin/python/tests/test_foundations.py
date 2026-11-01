from pathlib import Path
import unittest
from boundrelay_m3.paths import ROOT
class FoundationsTests(unittest.TestCase):
    def test_repository_paths_resolve_real_fixtures(self):
        self.assertTrue((ROOT/'fixtures/scenarios/order-brief.yaml').exists())
