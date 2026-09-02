import {describe, expect, it} from "vitest";

import {MemoryEventSink} from "../src/trace.js";

describe("MemoryEventSink", () => {
  it("assigns monotonic sequence numbers and validates each event", () => {
    let now = 0;
    let id = 0;
    const sink = new MemoryEventSink(
      "typescript",
      "run-1",
      () => new Date(now++).toISOString(),
      () => `evt-${++id}`,
    );

    sink.emit("run.created", {case_id: "billing-duplicate-charge"});
    sink.emit("run.started", {mode: "model"});
    sink.emit("run.completed", {status: "SUCCEEDED"});

    expect(sink.all().map((event) => event.sequence)).toEqual([1, 2, 3]);
  });

  it("returns defensive copies of stored events", () => {
    let id = 0;
    const sink = new MemoryEventSink(
      "typescript",
      "run-1",
      () => "2026-09-02T00:00:00.000Z",
      () => `evt-${++id}`,
    );

    sink.emit("run.created", {case_id: "billing-duplicate-charge"});
    const firstRead = sink.all();
    firstRead[0]!.data.case_id = "mutated";

    expect(sink.all()[0]!.data).toEqual({case_id: "billing-duplicate-charge"});
  });

  it("canonicalizes arbitrary event data to strict JSON values", () => {
    let id = 0;
    const sink = new MemoryEventSink(
      "typescript",
      "run-1",
      () => "2026-09-02T00:00:00.000Z",
      () => `evt-${++id}`,
    );
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;

    const event = sink.emit("run.created", {
      finite: 1.5,
      nan: Number.NaN,
      positive_infinity: Number.POSITIVE_INFINITY,
      negative_infinity: Number.NEGATIVE_INFINITY,
      bigint: 1n,
      missing: undefined,
      symbol: Symbol("unsupported"),
      callback: () => "unsupported",
      array: [undefined, 2n, Number.NaN],
      cycle,
    });

    expect(() => JSON.stringify(event)).not.toThrow();
    expect(JSON.parse(JSON.stringify(event)).data).toEqual({
      finite: 1.5,
      nan: null,
      positive_infinity: null,
      negative_infinity: null,
      bigint: null,
      missing: null,
      symbol: null,
      callback: null,
      array: [null, null, null],
      cycle: {self: null},
    });
  });
});
