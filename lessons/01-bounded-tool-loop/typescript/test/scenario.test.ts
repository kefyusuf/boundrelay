import {mkdtempSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {describe, expect, it} from "vitest";

import {findScenarioCase, loadScenario} from "../src/scenario.js";
import {ScriptedModelError, ScriptedModelProvider} from "../src/scripted-model.js";

describe("M1 scenario and scripted model", () => {
  it("loads the accepted agent success case without coercing its budgets", () => {
    expect(loadScenario().scenario_id).toBe("order-investigation");
    expect(findScenarioCase(loadScenario(), "agent-delayed-shipment")).toMatchObject({
      mode: "agent",
      max_steps: 3,
      max_tokens: 129,
      expected_model_steps: 3,
      expected_tokens_used: 129,
    });
  });

  it("rejects an unknown case id", () => {
    expect(() => findScenarioCase(loadScenario(), "missing-case")).toThrow("Unknown scenario case");
  });

  it("rejects malformed scenario values instead of coercing them", () => {
    const directory = mkdtempSync(join(tmpdir(), "boundrelay-m1-scenario-"));
    const path = join(directory, "scenario.yaml");
    writeFileSync(path, [
      'schema_version: "1.0"',
      'scenario_id: order-investigation',
      'cases:',
      '  - id: bad-case',
      '    mode: agent',
      '    request: bad',
      '    max_steps: "3"',
      '    max_tokens: 10',
      '    expected_status: FAILED',
      '    expected_failure_code: UNKNOWN_TOOL',
      '    expected_model_steps: 1',
      '    expected_tokens_used: 1',
      '    expected_tool_invocations: 0',
      '',
    ].join("\n"), "utf8");
    try {
      expect(() => loadScenario(path)).toThrow("max_steps");
    } finally {
      rmSync(directory, {recursive: true, force: true});
    }
  });

  it("rejects out-of-order scripted turns", async () => {
    const provider = ScriptedModelProvider.fromFile();
    await expect(provider.nextTurn({
      caseId: "agent-delayed-shipment",
      request: "Why is order ORD-1001 delayed?",
      modelStep: 2,
      observations: [],
    })).rejects.toThrow(ScriptedModelError);
  });

  it("rejects scripted trajectory exhaustion", async () => {
    const provider = ScriptedModelProvider.fromFile();
    const input = {caseId: "agent-delayed-shipment", request: "Why is order ORD-1001 delayed?", observations: []};
    await provider.nextTurn({...input, modelStep: 1});
    await provider.nextTurn({...input, modelStep: 2});
    await provider.nextTurn({...input, modelStep: 3});
    await expect(provider.nextTurn({...input, modelStep: 4})).rejects.toThrow(ScriptedModelError);
  });
});
