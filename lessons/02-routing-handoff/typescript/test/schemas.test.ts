import {describe, expect, it} from "vitest";
import {validateHandoff, validateHandoffResult, validateRouteDecision} from "../src/schemas.js";

const validHandoff = {
  schema_version: "1.0",
  handoff_id: "handoff-1",
  sender: "support-router",
  receiver: "billing-specialist",
  sender_intent: {route: "billing", confidence: 1, policy_outcome: "selected"},
  receiver_input: {ticket_id: "TCK-1001", request_text: "I was charged twice."},
};

describe("M2 shared schema boundaries", () => {
  it("reuses the M0 route decision boundary", () => {
    expect(validateRouteDecision({route: "billing", confidence: 0.8}).ok).toBe(true);
    expect(validateRouteDecision({route: "unknown", confidence: 0.8}).ok).toBe(false);
    expect(validateRouteDecision({route: "billing", confidence: 0.8, receiver: "billing-specialist"}).ok).toBe(false);
  });
  it("requires minimum receiver context and rejects extras", () => {
    expect(validateHandoff(validHandoff).ok).toBe(true);
    expect(validateHandoff({...validHandoff, receiver_input: {ticket_id: "TCK-1001"}}).ok).toBe(false);
    expect(validateHandoff({...validHandoff, receiver_input: {...validHandoff.receiver_input, model_prompt: "no"}}).ok).toBe(false);
  });
  it("validates canonical successful M2 result", () => {
    expect(validateHandoffResult({
      schema_version: "1.0", run_id: "run-1", scenario_id: "support-handoff",
      case_id: "code-billing-handoff", router_mode: "code", status: "SUCCEEDED",
      proposed_route: "billing", selected_route: "billing", receiver: "billing-specialist",
      fallback_applied: false, specialist_invoked: true, failure_code: null,
      trace_path: ".boundrelay/m2/trace.jsonl",
    }).ok).toBe(true);
  });
});
