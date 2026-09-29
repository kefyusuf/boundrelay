from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from boundrelay_m1.trace import MemoryEventSink, write_jsonl


def ids():
    n=0
    def next_id():
        nonlocal n; n+=1; return f"id-{n}"
    return next_id


class TraceTests(unittest.TestCase):
    def test_sanitizes_nested_non_finite_and_writes_strict_lf_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"trace.jsonl"
            sink=MemoryEventSink(run_id="run-1",source="python",clock=lambda: datetime(2026,9,29,tzinfo=timezone.utc),id_factory=ids())
            sink.emit("model.completed",{"case_id":"x","model_step":1,"turn":{"nested":{"value":float("nan")}}})
            write_jsonl(path,sink.events)
            raw=path.read_bytes()
            self.assertTrue(raw.endswith(b"\n")); self.assertNotIn(b"\r",raw)
            def reject(value): raise ValueError(value)
            value=json.loads(raw.decode().strip(),parse_constant=reject)
            self.assertIsNone(value["data"]["turn"]["nested"]["value"])
            self.assertEqual(value["sequence"],1)
