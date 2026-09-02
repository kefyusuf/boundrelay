from datetime import datetime, timezone
import unittest

from boundrelay_m0.trace import MemoryEventSink


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


if __name__ == "__main__":
    unittest.main()
