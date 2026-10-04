import {mkdtempSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {describe, expect, it} from "vitest";
import {findScenarioCase, loadFailureFixtures, loadScenario} from "../src/scenario.js";
import {ScriptedRouteError, ScriptedRouteProvider} from "../src/scripted-router.js";

describe("M2 scenario and scripted router", () => {
  it("loads the canonical fallback case without coercion", () => {
    expect(loadScenario().scenario_id).toBe("support-handoff");
    expect(findScenarioCase(loadScenario(), "model-low-confidence-fallback")).toMatchObject({
      router_mode: "model", expected_proposed_route: "billing", expected_confidence: 0.54,
      expected_selected_route: "general", expected_receiver: "general-specialist", expected_fallback_applied: true,
    });
  });
  it("loads exactly two isolated failure records", () => {
    const failures = loadFailureFixtures();
    expect(Object.keys(failures)).toEqual(["handoff-context-loss", "handoff-receiver-unavailable"]);
    expect(failures["code-billing-handoff"]).toBeUndefined();
  });
  it("rejects malformed scenario values instead of coercing them", () => {
    const dir = mkdtempSync(join(tmpdir(), "boundrelay-m2-scenario-"));
    const path = join(dir, "scenario.yaml");
    writeFileSync(path, 'schema_version: "1.0"\nscenario_id: support-handoff\nconfidence_threshold: "0.80"\nroute_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}\ncases: []\n', "utf8");
    try { expect(() => loadScenario(path)).toThrow("confidence_threshold"); }
    finally { rmSync(dir, {recursive: true, force: true}); }
  });
  it("rejects a numeric confidence threshold other than the accepted 0.80", () => {
    const dir = mkdtempSync(join(tmpdir(), "boundrelay-m2-threshold-"));
    const path = join(dir, "scenario.yaml");
    writeFileSync(path, 'schema_version: "1.0"\nscenario_id: support-handoff\nconfidence_threshold: 0.70\nroute_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}\ncases: []\n', "utf8");
    try { expect(() => loadScenario(path)).toThrow("confidence_threshold must be 0.80"); }
    finally { rmSync(dir, {recursive: true, force: true}); }
  });
  it("rejects unknown failure references and extra failure operators", () => {
    const dir = mkdtempSync(join(tmpdir(), "boundrelay-m2-failure-"));
    const scenarioPath = join(dir, "scenario.yaml");
    const failurePath = join(dir, "failures.yaml");
    writeFileSync(scenarioPath, 'schema_version: "1.0"\nscenario_id: support-handoff\nconfidence_threshold: 0.80\nroute_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}\ncases:\n  - id: bad\n    ticket_id: TCK-1001\n    request: bad\n    router_mode: code\n    expected_status: FAILED\n    expected_proposed_route: billing\n    expected_confidence: 1.0\n    expected_selected_route: billing\n    expected_receiver: billing-specialist\n    expected_policy_outcome: selected\n    expected_fallback_applied: false\n    expected_specialist_invoked: false\n    expected_failure_code: HANDOFF_CONTEXT_INVALID\n    failure_ref: missing\n', "utf8");
    writeFileSync(failurePath, 'schema_version: "1.0"\nscenario_id: support-handoff\nfailures:\n  known:\n    retry_count: 3\n', "utf8");
    try {
      expect(() => loadFailureFixtures(failurePath)).toThrow("unsupported failure operator");
      writeFileSync(failurePath, 'schema_version: "1.0"\nscenario_id: support-handoff\nfailures:\n  known:\n    omit_receiver_input_fields: [request_text]\n', "utf8");
      expect(() => loadScenario(scenarioPath, failurePath)).toThrow("Unknown failure_ref");
    } finally { rmSync(dir, {recursive: true, force: true}); }
  });
  it("rejects unknown receiver names", () => {
    const dir = mkdtempSync(join(tmpdir(), "boundrelay-m2-receiver-"));
    const path = join(dir, "scenario.yaml");
    writeFileSync(path, 'schema_version: "1.0"\nscenario_id: support-handoff\nconfidence_threshold: 0.80\nroute_receivers: {billing: unknown-specialist, technical: technical-specialist, general: general-specialist}\ncases: []\n', "utf8");
    try { expect(() => loadScenario(path)).toThrow("route_receivers.billing"); }
    finally { rmSync(dir, {recursive: true, force: true}); }
  });
  it("rejects duplicate scenario case ids", () => {
    const dir = mkdtempSync(join(tmpdir(), "boundrelay-m2-duplicate-"));
    const path = join(dir, "scenario.yaml");
    const caseBody = '    ticket_id: TCK-1001\n    request: duplicate\n    router_mode: code\n    expected_status: SUCCEEDED\n    expected_proposed_route: billing\n    expected_confidence: 1.0\n    expected_selected_route: billing\n    expected_receiver: billing-specialist\n    expected_policy_outcome: selected\n    expected_fallback_applied: false\n    expected_specialist_invoked: true\n';
    writeFileSync(path, 'schema_version: "1.0"\nscenario_id: support-handoff\nconfidence_threshold: 0.80\nroute_receivers: {billing: billing-specialist, technical: technical-specialist, general: general-specialist}\ncases:\n  - id: duplicate\n' + caseBody + '  - id: duplicate\n' + caseBody, "utf8");
    try { expect(() => loadScenario(path)).toThrow("case ids must be unique"); }
    finally { rmSync(dir, {recursive: true, force: true}); }
  });
  it("consumes each scripted decision at most once", async () => {
    const provider = ScriptedRouteProvider.fromFile();
    await expect(provider.nextDecision({caseId: "model-technical-handoff", request: "x"})).resolves.toEqual({route: "technical", confidence: 0.92});
    await expect(provider.nextDecision({caseId: "model-technical-handoff", request: "x"})).rejects.toThrow(ScriptedRouteError);
    await expect(provider.nextDecision({caseId: "missing", request: "x"})).rejects.toThrow(ScriptedRouteError);
  });
});
