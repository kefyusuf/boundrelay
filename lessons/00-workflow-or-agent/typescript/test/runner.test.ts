import {mkdtemp, readFile} from "node:fs/promises";
import net from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {afterAll, beforeAll, describe, expect, it, vi} from "vitest";

import type {RunEvent} from "../src/types.js";

type RunScenarioCase = typeof import("../src/runner.js").runScenarioCase;
type RecordingDispatcher = typeof import("../src/specialists.js").RecordingSpecialistDispatcher;

let runScenarioCase: RunScenarioCase;
let RecordingSpecialistDispatcher: RecordingDispatcher;
let restoreSocketConnect: (() => void) | undefined;

function fixedIds(prefix: string): () => string {
  let sequence = 0;
  return () => `${prefix}-${++sequence}`;
}

async function readEvents(path: string): Promise<RunEvent[]> {
  const content = await readFile(path, "utf8");
  return content.trim().split("\n").map((line) => JSON.parse(line) as RunEvent);
}

const canonicalRuns = [
  ["billing-duplicate-charge", "deterministic"],
  ["billing-duplicate-charge", "model"],
  ["technical-login-error", "deterministic"],
  ["technical-login-error", "model"],
  ["general-opening-hours", "deterministic"],
  ["general-opening-hours", "model"],
  ["invalid-model-route", "model"],
] as const;

beforeAll(async () => {
  const socketConnect = vi.spyOn(net.Socket.prototype, "connect").mockImplementation(() => {
    throw new Error("network access is forbidden");
  });
  restoreSocketConnect = () => socketConnect.mockRestore();
  vi.stubGlobal("fetch", async () => {
    throw new Error("network access is forbidden");
  });

  await expect(import("./offline-import-probe.js")).rejects.toThrow("network access is forbidden");

  ({runScenarioCase} = await import("../src/runner.js"));
  ({RecordingSpecialistDispatcher} = await import("../src/specialists.js"));
});

afterAll(() => {
  restoreSocketConnect?.();
  vi.unstubAllGlobals();
});

describe("runScenarioCase", () => {
  it("runs a valid model route with one terminal event and one real dispatch", async () => {
    const directory = await mkdtemp(join(tmpdir(), "boundrelay-ts-valid-"));
    const tracePath = join(directory, "trace.jsonl");
    const dispatcher = new RecordingSpecialistDispatcher();

    const result = await runScenarioCase({
      mode: "model",
      caseId: "billing-duplicate-charge",
      tracePath,
      specialistDispatcher: dispatcher,
      clock: () => new Date("2026-09-02T00:00:00Z"),
      idFactory: fixedIds("valid"),
    });
    const events = await readEvents(tracePath);

    expect(result.status).toBe("SUCCEEDED");
    expect(result.selected_route).toBe("billing");
    expect(dispatcher.invocations).toEqual([
      {route: "billing", request: "I was charged twice for the same invoice."},
    ]);
    expect(events.map((event) => event.sequence)).toEqual(events.map((_, index) => index + 1));
    expect(events.filter((event) => ["run.completed", "run.failed"].includes(event.type))).toHaveLength(1);
    expect(events.at(-1)?.type).toBe("run.completed");
  });

  it("fails closed for an invalid model route without a specialist step or dispatch", async () => {
    const directory = await mkdtemp(join(tmpdir(), "boundrelay-ts-invalid-"));
    const tracePath = join(directory, "trace.jsonl");
    const dispatcher = new RecordingSpecialistDispatcher();

    const result = await runScenarioCase({
      mode: "model",
      caseId: "invalid-model-route",
      tracePath,
      specialistDispatcher: dispatcher,
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
    expect(dispatcher.invocations).toEqual([]);
    expect(events.some((event) => event.type === "route.rejected")).toBe(true);
    expect(events.filter((event) => ["run.completed", "run.failed"].includes(event.type))).toHaveLength(1);
    expect(events.at(-1)?.type).toBe("run.failed");
    expect(events.some((event) => {
      const step = event.data.step;
      return typeof step === "string" && step.startsWith("specialist.");
    })).toBe(false);
  });

  it("records a BigInt model decision as strict JSON and fails closed", async () => {
    const directory = await mkdtemp(join(tmpdir(), "boundrelay-ts-bigint-"));
    const tracePath = join(directory, "trace.jsonl");

    const result = await runScenarioCase({
      mode: "model",
      caseId: "billing-duplicate-charge",
      tracePath,
      decisionProvider: {
        classify: async () => ({route: "billing", confidence: 2n}),
      },
      clock: () => new Date("2026-09-02T00:00:00Z"),
      idFactory: fixedIds("bigint"),
    });
    const events = await readEvents(tracePath);
    const modelCompleted = events.find((event) => event.type === "model.completed");

    expect(result).toMatchObject({
      status: "FAILED",
      selected_route: null,
      specialist_invoked: false,
      failure_code: "INVALID_ROUTE_DECISION",
    });
    expect(modelCompleted?.data.decision).toEqual({route: "billing", confidence: null});
    expect(events.at(-1)?.type).toBe("run.failed");
    expect(events.some((event) => {
      const step = event.data.step;
      return typeof step === "string" && step.startsWith("specialist.");
    })).toBe(false);
  });

  it.each(canonicalRuns)("keeps canonical %s/%s execution offline", async (caseId, mode) => {
    const directory = await mkdtemp(join(tmpdir(), "boundrelay-ts-offline-"));
    const tracePath = join(directory, `${caseId}-${mode}.jsonl`);

    await runScenarioCase({
      mode,
      caseId,
      tracePath,
      clock: () => new Date("2026-09-02T00:00:00Z"),
      idFactory: fixedIds(`offline-${caseId}-${mode}`),
    });
  });
});
