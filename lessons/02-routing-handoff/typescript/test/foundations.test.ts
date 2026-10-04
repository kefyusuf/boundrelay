import {describe, expect, it} from "vitest";
import {readFileSync} from "node:fs";
import {parse} from "yaml";
import {loadScenario, findScenarioCase, loadFailureFixtures} from "../src/scenario.js";
import {validateHandoff, validateRouteDecision} from "../src/schemas.js";
import {applyConfidencePolicy} from "../src/policy.js";
import {classifyWithCode, ScriptedRouteProvider} from "../src/scripted-router.js";
import {createReceiverDirectory} from "../src/receivers.js";
import {SCENARIO_PATH, FAILURE_PATH} from "../src/paths.js";

describe("M2 foundations", () => {
  it("accepts explicit null failure codes on success while rejecting failure fields", () => {
    const raw = parse(readFileSync(SCENARIO_PATH, "utf8"));
    raw.cases[0].expected_failure_code = null;
    expect(findScenarioCase(loadScenario(raw), raw.cases[0].id).expected_status).toBe("SUCCEEDED");
    raw.cases[0].expected_failure_code = "HANDOFF_CONTEXT_INVALID";
    expect(() => loadScenario(raw)).toThrow("success case cannot define failure fields");
    raw.cases[0].expected_failure_code = null;
    raw.cases[0].failure_ref = "handoff-context-loss";
    expect(() => loadScenario(raw)).toThrow("success case cannot define failure fields");
  });
  it("loads the canonical fallback and isolates failures", () => {
    expect(findScenarioCase(loadScenario(), "model-low-confidence-fallback")).toMatchObject({router_mode: "model", expected_proposed_route: "billing", expected_confidence: 0.54, expected_selected_route: "general", expected_receiver: "general-specialist", expected_fallback_applied: true});
    expect(Object.keys(loadFailureFixtures())).toEqual(["handoff-context-loss", "handoff-receiver-unavailable"]);
    expect(loadFailureFixtures()["code-billing-handoff"]).toBeUndefined();
  });
  it("rejects malformed scenario fields without coercion", () => {
    const raw = parse(readFileSync(SCENARIO_PATH, "utf8"));
    for (const value of ["0.80", true, 0.79]) expect(() => loadScenario({...raw, confidence_threshold: value})).toThrow();
    expect(() => loadScenario({...raw, cases: [...raw.cases, raw.cases[0]]})).toThrow();
    for (const [key, value] of [["router_mode", "auto"], ["expected_fallback_applied", "false"], ["ticket_id", "bad"], ["failure_ref", "unknown"]]) {
      const bad = structuredClone(raw); bad.cases[0][key as string] = value;
      expect(() => loadScenario(bad)).toThrow();
    }
  });
  it("rejects unknown and cross-case failure operators", () => {
    const raw = parse(readFileSync(FAILURE_PATH, "utf8"));
    const bad = structuredClone(raw); bad.failures["handoff-context-loss"].retry = true;
    expect(() => loadFailureFixtures(bad)).toThrow();
    expect(() => loadFailureFixtures({...raw, failures: {...raw.failures, "code-billing-handoff": {unavailable_receivers: ["billing-specialist"]}}})).toThrow();
  });
  it("rejects missing or additional receiver context", () => {
    const base = {schema_version: "1.0", handoff_id: "h", sender: "support-router", receiver: "billing-specialist", sender_intent: {route: "billing", confidence: .8, policy_outcome: "selected"}, receiver_input: {ticket_id: "TCK-1001", request_text: "invoice"}};
    expect(validateHandoff(base).ok).toBe(true);
    expect(validateHandoff({...base, receiver_input: {ticket_id: "TCK-1001"}}).ok).toBe(false);
    expect(validateHandoff({...base, receiver_input: {...base.receiver_input, prompt: "secret"}}).ok).toBe(false);
    for (const confidence of [NaN, Infinity, "0.8", true, -1, 2]) expect(validateRouteDecision({route: "billing", confidence}).ok).toBe(false);
    expect(validateRouteDecision({route: "billing", confidence: .8, receiver: "general-specialist"}).ok).toBe(false);
  });
  it("pins equality and fallback independently of scripted cases", () => {
    expect(applyConfidencePolicy({route: "billing", confidence: .8})).toEqual({proposedRoute: "billing", selectedRoute: "billing", confidence: .8, receiver: "billing-specialist", policyOutcome: "selected", fallbackApplied: false});
    expect(applyConfidencePolicy({route: "billing", confidence: .79})).toMatchObject({selectedRoute: "general", receiver: "general-specialist", policyOutcome: "fallback", fallbackApplied: true});
    for (const route of ["technical", "general"] as const) expect(applyConfidencePolicy({route, confidence: 1}).receiver).toBe(`${route}-specialist`);
  });
  it("uses the deterministic keyword baseline", () => {
    expect(classifyWithCode("I was billed twice")).toEqual({route: "billing", confidence: 1});
    expect(classifyWithCode("The app is broken").route).toBe("technical");
    expect(classifyWithCode("Hello").route).toBe("general");
  });
  it("consumes scripted decisions once without heuristic fallback", async () => {
    const provider = ScriptedRouteProvider.fromFile();
    expect(await provider.nextDecision({caseId: "model-technical-handoff", request: "ignored"})).toEqual({route: "technical", confidence: .92});
    await expect(provider.nextDecision({caseId: "model-technical-handoff", request: "ignored"})).rejects.toThrow();
    await expect(provider.nextDecision({caseId: "unknown", request: "invoice"})).rejects.toThrow();
  });
  it("resolves only available named receivers", async () => {
    const directory = createReceiverDirectory(["billing-specialist"]);
    expect(directory.resolve("billing-specialist")).toBeUndefined();
    expect(directory.resolve("unknown")).toBeUndefined();
    for (const name of ["technical-specialist", "general-specialist"]) await directory.resolve(name)!.handle({ticket_id: "TCK-1001", request_text: "hello"});
  });
});
