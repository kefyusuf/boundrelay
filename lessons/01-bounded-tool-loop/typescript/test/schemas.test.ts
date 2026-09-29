import {describe, expect, it} from "vitest";

import {validateModelTurn, validateRunResult, validateToolArguments} from "../src/schemas.js";

describe("M1 shared schema boundaries", () => {
  it("keeps unknown tool names structurally valid at the outer model boundary", () => {
    expect(validateModelTurn({
      schema_version: "1.0",
      decision: {kind: "tool_call", call_id: "call-1", tool: "unknown-tool", arguments: {}},
      usage: {input_tokens: 1, output_tokens: 0},
    }).ok).toBe(true);
  });

  it("enforces tool-specific identifier formats and additional-property rejection", () => {
    expect(validateToolArguments("lookup_order", {order_id: "ORD-1001"}).ok).toBe(true);
    expect(validateToolArguments("lookup_order", {order_id: "1001"}).ok).toBe(false);
    expect(validateToolArguments("lookup_order", {order_id: "ORD-1001", extra: true}).ok).toBe(false);
    expect(validateToolArguments("lookup_shipment", {shipment_id: "SHP-1001"}).ok).toBe(true);
  });

  it("validates the canonical successful M1 result shape", () => {
    expect(validateRunResult({
      schema_version: "1.0",
      run_id: "run-1",
      scenario_id: "order-investigation",
      case_id: "agent-delayed-shipment",
      mode: "agent",
      status: "SUCCEEDED",
      answer: "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
      failure_code: null,
      model_steps: 3,
      tokens_used: 129,
      tool_invocations: 2,
      trace_path: ".boundrelay/m1/trace.jsonl",
    }).ok).toBe(true);
  });
});
