import {mkdtemp, readFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {describe, expect, it} from "vitest";

import {MemoryEventSink, writeJsonl} from "../src/trace.js";

function ids(): () => string {
  let sequence = 0;
  return () => `id-${++sequence}`;
}

describe("M1 trace safety", () => {
  it("sanitizes nested BigInt and writes strict LF JSONL", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-trace-"));
    const tracePath = join(directory, "trace.jsonl");
    const sink = new MemoryEventSink({
      runId: "run-1",
      source: "typescript",
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids(),
    });

    sink.emit("model.completed", {
      case_id: "x",
      model_step: 1,
      turn: {nested: {value: 2n}},
    });
    await writeJsonl(tracePath, sink.events);

    const content = await readFile(tracePath, "utf8");
    expect(content.endsWith("\n")).toBe(true);
    expect(content.includes("\r")).toBe(false);
    const value = JSON.parse(content.trim());
    expect(value.data.turn.nested.value).toBe(null);
  });
});
