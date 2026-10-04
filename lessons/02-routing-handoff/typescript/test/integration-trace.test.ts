import {it, expect} from "vitest";
import {MemoryEventSink} from "../src/trace.js";
it("snapshots JSON-safe candidates and isolates returned events", () => {
  const sink = new MemoryEventSink({runId: "run", source: "typescript"});
  const data = {decision: {route: "billing", confidence: Infinity}};
  sink.emit("model.completed", data);
  data.decision.route = "changed";
  const copy = sink.events;
  copy[0]!.data.changed = true;
  expect(sink.events[0]!.data).toEqual({decision: {route: "billing", confidence: null}});
  expect(() => new MemoryEventSink({runId: "", source: "typescript"}).emit("run.started", {})).toThrow();
});
