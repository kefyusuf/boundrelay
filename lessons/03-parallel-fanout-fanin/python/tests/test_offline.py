import json,subprocess,sys
from pathlib import Path
import unittest
class OfflineTests(unittest.TestCase):
    def test_fresh_import_guard_and_all_six_offline_runs(self):
        process=subprocess.run([sys.executable,str(Path(__file__).with_name('offline_runner.py'))],capture_output=True,text=True,check=True,timeout=15)
        self.assertEqual(json.loads(process.stdout),{'import_probe_blocked':True,'statuses':['SUCCEEDED','SUCCEEDED','SUCCEEDED','PARTIAL','FAILED','PARTIAL']})
