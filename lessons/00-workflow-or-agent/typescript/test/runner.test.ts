import {mkdtemp, readFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {describe, expect, it} from "vitest";

import {runScenarioCase} from "../src/runner.js";
import type {RunEvent} from "../src/types.js";

function fixedIds(prefix: string): () => string {
  let sequence = 0;
  return () => `${prefix}-${++sequence}`;
}

async function readEvents(path: string): Promise<RunEvent[]> {
  const content = await readFile(path, "utf8");
  return content.trim().split("\n").map((line) => JSON.parse(line) as RunEvent);
}

describe("runScenarioCase", () => {
  it("runs a valid model route with one terminal event", async () => {
    const directory = await mkdtemp(join(tmpdir(), "boundrelay-ts-valid-"));
    const tracePath = join(directory, "trace.jsonl");

    const result = await runScenarioCase({
      mode: "model",
      caseId: "billing-duplicate-charge",
      tracePath,
      clock: () => new Date("2026-09-02T00:00:00Z"),
      idFactory: fixedIds("valid"),
    });
    const events = await readEvents(tracePath);

    expect(result.status).toBe("SUCCEEDED");
    expect(result.selected_route).toBe("billing");
    expect(events.map((event) => event.sequence)).toEqual(events.map((_, index) => index + 1));
    expect(events.filter((event) => ["run.completed", "run.failed"].includes(event.type))).toHaveLength(1);
    expect(events.at(-1)?.type).toBe("run.completed");
  });

  it("fails closed for an invalid model route without a specialist step", async () => {
    const directory = await mkdtemp(join(tmpdir(), "boundrelay-ts-invalid-"));
    const tracePath = join(directory, "trace.jsonl");

    const result = await runScenarioCase({
      mode: "model",
      caseId: "invalid-model-route",
      tracePath,
      clock: () => new Date("2026-09-02T00:00:00Z"),
      idFactory: fixedIds("invalid"),
    });
    const events = await readEvents(tracePath);

    expect(result).toMatchObject({
      status: "FAILED",
      selected_route: null,
      specialist_invoked: false,
      failure_code: "INVALID_ROUTE_DECISION",
    });
    expect(events.some((event) => event.type === "route.rejected")).toBe(true);
    expect(events.filter((event) => ["run.completed", "run.failed"].includes(event.type))).toHaveLength(1);
    expect(events.at(-1)?.type).toBe("run.failed");
    expect(events.some((event) => {
      const step = event.data.step;
      return typeof step === "string" && step.startsWith("specialist.");
    })).toBe(false);
  });
});
