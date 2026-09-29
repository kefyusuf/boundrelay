import {mkdtemp, readFile} from "node:fs/promises";
import net from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {afterAll, beforeAll, describe, expect, it} from "vitest";

import type {ModelInput, ModelProvider, RunEvent, ToolRegistry} from "../src/types.js";

type RunScenarioCase = typeof import("../src/runner.js").runScenarioCase;

let runScenarioCase: RunScenarioCase;
const originalConnect = net.Socket.prototype.connect;
const originalFetch = globalThis.fetch;

function ids(prefix: string): () => string {
  let sequence = 0;
  return () => `${prefix}-${++sequence}`;
}

async function events(path: string): Promise<RunEvent[]> {
  const text = await readFile(path, "utf8");
  return text.trim().split("\n").map((line: string) => JSON.parse(line) as RunEvent);
}

class RecordingProvider implements ModelProvider {
  readonly inputs: ModelInput[] = [];
  readonly turns = [
    {
      schema_version: "1.0",
      decision: {
        kind: "tool_call",
        call_id: "call-1",
        tool: "lookup_order",
        arguments: {order_id: "ORD-1001"},
      },
      usage: {input_tokens: 50, output_tokens: 10},
    },
    {
      schema_version: "1.0",
      decision: {
        kind: "tool_call",
        call_id: "call-2",
        tool: "lookup_shipment",
        arguments: {shipment_id: "SHP-1001"},
      },
      usage: {input_tokens: 30, output_tokens: 10},
    },
    {
      schema_version: "1.0",
      decision: {
        kind: "final",
        answer: "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
      },
      usage: {input_tokens: 20, output_tokens: 9},
    },
  ];

  async nextTurn(input: ModelInput): Promise<unknown> {
    this.inputs.push(structuredClone(input));
    return structuredClone(this.turns[input.modelStep - 1]);
  }
}

beforeAll(async () => {
  net.Socket.prototype.connect = function blockedConnect() {
    throw new Error("network access is forbidden");
  } as any;
  globalThis.fetch = async () => {
    throw new Error("network access is forbidden");
  };

  await expect(import("./offline-import-probe.js")).rejects.toThrow("network access is forbidden");
  ({runScenarioCase} = await import("../src/runner.js"));
});

afterAll(() => {
  net.Socket.prototype.connect = originalConnect;
  globalThis.fetch = originalFetch;
});

describe("M1 runner", () => {
  it("runs direct baseline without model events", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-direct-"));
    const tracePath = join(directory, "trace.jsonl");
    const result = await runScenarioCase({
      mode: "direct",
      caseId: "direct-order-status",
      tracePath,
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids("d"),
    });
    const trace = await events(tracePath);

    expect(result).toMatchObject({
      status: "SUCCEEDED",
      answer: "Order ORD-1001 status is SHIPPED.",
      failure_code: null,
      model_steps: 0,
      tokens_used: 0,
      tool_invocations: 1,
    });
    expect(trace.filter((event) => event.type.startsWith("model."))).toHaveLength(0);
    expect(trace.filter((event) => event.type === "tool.requested")).toHaveLength(1);
    expect(trace.at(-1)?.type).toBe("run.completed");
  });

  it("runs successful agent loop and passes observations to later turns", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-agent-"));
    const tracePath = join(directory, "trace.jsonl");
    const provider = new RecordingProvider();
    const result = await runScenarioCase({
      mode: "agent",
      caseId: "agent-delayed-shipment",
      tracePath,
      modelProvider: provider,
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids("a"),
    });
    const trace = await events(tracePath);

    expect(result).toMatchObject({
      status: "SUCCEEDED",
      answer: "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
      failure_code: null,
      model_steps: 3,
      tokens_used: 129,
      tool_invocations: 2,
    });
    expect(trace.filter((event) => event.type === "tool.requested").map((event) => event.data.tool)).toEqual([
      "lookup_order",
      "lookup_shipment",
    ]);
    expect(trace.filter((event) => event.type === "budget.consumed").map((event) => event.data)).toEqual([
      {model_steps: 1, max_steps: 3, tokens_used: 60, max_tokens: 129},
      {model_steps: 2, max_steps: 3, tokens_used: 100, max_tokens: 129},
      {model_steps: 3, max_steps: 3, tokens_used: 129, max_tokens: 129},
    ]);
    expect(provider.inputs[1]?.observations[0]).toEqual({
      call_id: "call-1",
      tool: "lookup_order",
      output: {order_id: "ORD-1001", status: "SHIPPED", shipment_id: "SHP-1001"},
    });
    expect(provider.inputs[2]?.observations[1]).toEqual({
      call_id: "call-2",
      tool: "lookup_shipment",
      output: {shipment_id: "SHP-1001", status: "DELAYED", reason: "WEATHER"},
    });
    expect(trace.some((event) => event.type.startsWith("step."))).toBe(false);
    expect(trace.at(-1)?.type).toBe("run.completed");
  });

  const failures = [
    ["agent-unknown-tool", "UNKNOWN_TOOL", 0, 1, 25],
    ["agent-invalid-arguments", "INVALID_TOOL_ARGUMENTS", 0, 1, 25],
    ["agent-tool-timeout", "TOOL_TIMEOUT", 1, 1, 25],
    ["agent-tool-failure", "TOOL_EXECUTION_FAILED", 1, 1, 25],
    ["agent-step-budget", "STEP_BUDGET_EXCEEDED", 1, 2, 50],
    ["agent-token-budget", "TOKEN_BUDGET_EXCEEDED", 1, 2, 75],
  ] as const;

  it.each(failures)(
    "fails canonical %s with %s",
    async (caseId: string, code: string, invocations: number, steps: number, tokens: number) => {
      const directory = await mkdtemp(join(tmpdir(), "br-m1-fail-"));
      const tracePath = join(directory, `${caseId}.jsonl`);
      const result = await runScenarioCase({
        mode: "agent",
        caseId,
        tracePath,
        clock: () => new Date("2026-09-29T00:00:00Z"),
        idFactory: ids(caseId),
      });
      const trace = await events(tracePath);

      expect(result).toMatchObject({
        status: "FAILED",
        failure_code: code,
        tool_invocations: invocations,
        model_steps: steps,
        tokens_used: tokens,
      });
      expect(trace.filter((event) => event.type === "tool.requested")).toHaveLength(invocations);
      if (code === "TOOL_TIMEOUT" || code === "TOOL_EXECUTION_FAILED") {
        expect(trace.filter((event) => event.type === "tool.failed")).toHaveLength(1);
      }
      expect(trace.at(-1)?.type).toBe("run.failed");
    },
  );

  it("rejects invalid model turn without counting usage or dispatching", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-invalid-model-"));
    const tracePath = join(directory, "trace.jsonl");
    const provider: ModelProvider = {
      nextTurn: async () => ({
        schema_version: "1.0",
        decision: {kind: "final", answer: "x"},
        usage: {input_tokens: "bad", output_tokens: 999},
      }),
    };
    const result = await runScenarioCase({
      mode: "agent",
      caseId: "agent-delayed-shipment",
      tracePath,
      modelProvider: provider,
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids("im"),
    });
    const trace = await events(tracePath);

    expect(result).toMatchObject({
      status: "FAILED",
      failure_code: "INVALID_MODEL_DECISION",
      tokens_used: 0,
      tool_invocations: 0,
      model_steps: 1,
    });
    expect(trace.filter((event) => event.type === "budget.consumed")).toHaveLength(0);
    expect(trace.filter((event) => event.type === "tool.requested")).toHaveLength(0);
  });

  it("maps provider errors to INVALID_MODEL_DECISION with model.failed", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-provider-fail-"));
    const tracePath = join(directory, "trace.jsonl");
    const provider: ModelProvider = {
      nextTurn: async () => { throw new Error("script exhausted"); },
    };
    const result = await runScenarioCase({
      mode: "agent",
      caseId: "agent-delayed-shipment",
      tracePath,
      modelProvider: provider,
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids("pf"),
    });
    const trace = await events(tracePath);

    expect(result).toMatchObject({
      status: "FAILED",
      failure_code: "INVALID_MODEL_DECISION",
      model_steps: 1,
      tokens_used: 0,
      tool_invocations: 0,
    });
    expect(trace.filter((event) => event.type === "model.failed")).toHaveLength(1);
  });

  it("uses same timeout executor for direct mode", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-direct-timeout-"));
    const tracePath = join(directory, "trace.jsonl");
    const registry: ToolRegistry = {
      resolve: (name) => name === "lookup_order" ? {
        name: "lookup_order",
        sideEffect: "READ_ONLY",
        timeoutMs: 5,
        validateArguments: (value) => ({ok: true, value: value as Record<string, unknown>}),
        invoke: async () => new Promise<Record<string, unknown>>(() => {}),
      } : undefined,
    };
    const result = await runScenarioCase({
      mode: "direct",
      caseId: "direct-order-status",
      tracePath,
      toolRegistry: registry,
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids("dt"),
    });
    const trace = await events(tracePath);

    expect(result).toMatchObject({
      status: "FAILED",
      failure_code: "TOOL_TIMEOUT",
      tool_invocations: 1,
      model_steps: 0,
      tokens_used: 0,
    });
    expect(trace.filter((event) => event.type.startsWith("model."))).toHaveLength(0);
  });

  it("keeps equality boundaries valid on canonical success", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-eq-"));
    const tracePath = join(directory, "trace.jsonl");
    const result = await runScenarioCase({
      mode: "agent",
      caseId: "agent-delayed-shipment",
      tracePath,
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids("eq"),
    });

    expect(result.model_steps).toBe(3);
    expect(result.tokens_used).toBe(129);
    expect(result.status).toBe("SUCCEEDED");
  });

  it.each([
    ["direct-order-status", "direct"],
    ["agent-delayed-shipment", "agent"],
    ["agent-unknown-tool", "agent"],
    ["agent-invalid-arguments", "agent"],
    ["agent-tool-timeout", "agent"],
    ["agent-tool-failure", "agent"],
    ["agent-step-budget", "agent"],
    ["agent-token-budget", "agent"],
  ] as const)("keeps %s/%s offline", async (caseId: string, mode: "direct" | "agent") => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-offline-"));
    await runScenarioCase({
      mode,
      caseId,
      tracePath: join(directory, "trace.jsonl"),
      clock: () => new Date("2026-09-29T00:00:00Z"),
      idFactory: ids(`off-${caseId}`),
    });
  });
});
