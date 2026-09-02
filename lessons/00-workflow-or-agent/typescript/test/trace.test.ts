import {describe, expect, it} from "vitest";

import {MemoryEventSink} from "../src/trace.js";

describe("MemoryEventSink", () => {
  it("assigns monotonically increasing sequences and validates events", () => {
    let nextId = 0;
    const sink = new MemoryEventSink({
      runId: "run-fixed",
      source: "typescript",
      clock: () => new Date("2026-09-02T00:00:00Z"),
      idFactory: () => `evt-${++nextId}`,
    });

    sink.emit("run.created", {});
    sink.emit("run.started", {});

    expect(sink.events.map((event) => event.sequence)).toEqual([1, 2]);
    expect(sink.events.map((event) => event.event_id)).toEqual(["evt-1", "evt-2"]);
  });
});
