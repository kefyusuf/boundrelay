import {describe, expect, it} from "vitest";

import {validateRouteDecision, validateRunEvent, validateRunResult} from "../src/schemas.js";

describe("shared schema adapters", () => {
  it("accepts valid shared contract values", () => {
    expect(validateRouteDecision({route: "billing", confidence: 0.9}).ok).toBe(true);
    expect(validateRunEvent({
      schema_version: "1.0",
      event_id: "evt-1",
      run_id: "run-1",
      sequence: 1,
      type: "run.created",
      timestamp: "2026-09-02T00:00:00.000Z",
      source: "typescript",
      data: {},
    }).ok).toBe(true);
    expect(validateRunResult({
      schema_version: "1.0",
      run_id: "run-1",
      scenario_id: "support-triage",
      case_id: "billing-duplicate-charge",
      mode: "deterministic",
      status: "SUCCEEDED",
      selected_route: "billing",
      specialist_invoked: true,
      failure_code: null,
      trace_path: ".boundrelay/m0/trace.jsonl",
    }).ok).toBe(true);
  });

  it("rejects invalid route and inconsistent result values", () => {
    expect(validateRouteDecision({route: "unknown", confidence: 0.9}).ok).toBe(false);
    expect(validateRunResult({
      schema_version: "1.0",
      run_id: "run-1",
      scenario_id: "support-triage",
      case_id: "invalid-model-route",
      mode: "model",
      status: "FAILED",
      selected_route: "billing",
      specialist_invoked: true,
      failure_code: null,
      trace_path: ".boundrelay/m0/trace.jsonl",
    }).ok).toBe(false);
  });
});
