from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from boundrelay_m0.trace import MemoryEventSink, write_jsonl


class TraceTests(unittest.TestCase):
    def test_assigns_monotonic_sequences_and_validates_events(self) -> None:
        ids = iter(["evt-1", "evt-2"])
        sink = MemoryEventSink(
            run_id="run-fixed",
            source="python",
            clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc),
            id_factory=lambda: next(ids),
        )

        sink.emit("run.created", {})
        sink.emit("run.started", {})

        self.assertEqual([event["sequence"] for event in sink.events], [1, 2])
        self.assertEqual([event["event_id"] for event in sink.events], ["evt-1", "evt-2"])

    def test_canonicalizes_unserializable_oversized_integer_before_storage(self) -> None:
        sink = MemoryEventSink(
            run_id="run-fixed",
            source="python",
            clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc),
            id_factory=lambda: "evt-1",
        )

        event = sink.emit(
            "model.completed",
            {
                "case_id": "billing-duplicate-charge",
                "decision": {"route": "billing", "confidence": 10**10000},
            },
        )
        decision = event["data"]["decision"]
        self.assertIsInstance(decision, dict)
        self.assertIsNone(decision["confidence"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            write_jsonl(path, sink.events)
            parsed = json.loads(path.read_text(encoding="utf-8"))

        self.assertIsNone(parsed["data"]["decision"]["confidence"])

    def test_lone_surrogate_is_escaped_before_utf8_trace_write(self) -> None:
        sink = MemoryEventSink(
            run_id="run-fixed",
            source="python",
            clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc),
            id_factory=lambda: "evt-1",
        )
        sink.emit(
            "model.completed",
            {
                "case_id": "invalid-model-route",
                "decision": {"route": "\ud800", "confidence": 0.9},
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            write_jsonl(path, sink.events)
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)

        self.assertIn("\\ud800", raw)
        self.assertEqual(parsed["data"]["decision"]["route"], "\ud800")


if __name__ == "__main__":
    unittest.main()
