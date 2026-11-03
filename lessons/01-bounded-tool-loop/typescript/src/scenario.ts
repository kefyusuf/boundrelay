import {readFileSync} from "node:fs";

import {parse} from "yaml";

import {SCENARIO_PATH} from "./paths.js";
import {STEP_KINDS, type AttributionTables} from "./attribution.js";
import {
  FAILURE_CODES,
  TOOL_NAMES,
  type DirectCall,
  type FailureCode,
  type RunMode,
  type ScenarioCase,
  type ScenarioDefinition,
  type ToolName,
} from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${key} must be a non-empty string.`);
  }
  return value;
}

function requireNonNegativeInteger(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`${key} must be a non-negative integer.`);
  }
  return value as number;
}

function isToolName(value: unknown): value is ToolName {
  return typeof value === "string" && (TOOL_NAMES as readonly string[]).includes(value);
}

function isFailureCode(value: unknown): value is FailureCode {
  return typeof value === "string" && (FAILURE_CODES as readonly string[]).includes(value);
}

function parseMode(value: unknown): RunMode {
  if (value !== "direct" && value !== "agent") {
    throw new Error("mode must be direct or agent.");
  }
  return value;
}

function parseDirectCall(value: unknown): DirectCall {
  if (!isRecord(value)) {
    throw new Error("direct_call must be an object.");
  }
  const tool = value.tool;
  if (!isToolName(tool)) {
    throw new Error("direct_call.tool must name an M1 tool.");
  }
  if (!isRecord(value.arguments)) {
    throw new Error("direct_call.arguments must be an object.");
  }
  return {
    call_id: requireString(value, "call_id"),
    tool,
    arguments: structuredClone(value.arguments),
  };
}

function parseCase(raw: unknown): ScenarioCase {
  if (!isRecord(raw)) {
    throw new Error("Scenario case must be an object.");
  }

  const common = {
    id: requireString(raw, "id"),
    mode: parseMode(raw.mode),
    request: requireString(raw, "request"),
    max_steps: requireNonNegativeInteger(raw, "max_steps"),
    max_tokens: requireNonNegativeInteger(raw, "max_tokens"),
    expected_model_steps: requireNonNegativeInteger(raw, "expected_model_steps"),
    expected_tokens_used: requireNonNegativeInteger(raw, "expected_tokens_used"),
    expected_tool_invocations: requireNonNegativeInteger(raw, "expected_tool_invocations"),
  };

  if (raw.expected_status === "SUCCEEDED") {
    if (typeof raw.expected_answer !== "string" || raw.expected_answer.length === 0) {
      throw new Error(`${common.id} expected_answer must be a non-empty string.`);
    }
    if (raw.expected_failure_code !== undefined) {
      throw new Error(`${common.id} cannot define expected_failure_code on success.`);
    }
    if (common.mode === "direct") {
      return {...common, expected_status: "SUCCEEDED", expected_answer: raw.expected_answer, direct_call: parseDirectCall(raw.direct_call)};
    }
    if (raw.direct_call !== undefined) {
      throw new Error(`${common.id} agent mode cannot define direct_call.`);
    }
    return {...common, expected_status: "SUCCEEDED", expected_answer: raw.expected_answer};
  }

  if (raw.expected_status === "FAILED") {
    if (common.mode !== "agent") {
      throw new Error(`${common.id} failed canonical cases must use agent mode.`);
    }
    if (!isFailureCode(raw.expected_failure_code)) {
      throw new Error(`${common.id} expected_failure_code is unsupported.`);
    }
    if (raw.expected_answer !== undefined || raw.direct_call !== undefined) {
      throw new Error(`${common.id} failed case cannot define success-only fields.`);
    }
    return {...common, mode: "agent", expected_status: "FAILED", expected_failure_code: raw.expected_failure_code};
  }

  throw new Error(`${common.id} expected_status must be SUCCEEDED or FAILED.`);
}

export function parseAttribution(raw: unknown): AttributionTables | null {
  if (raw === undefined || raw === null) {
    return null;
  }
  if (!isRecord(raw) || Object.keys(raw).sort().join("|") !== "latency_ms|price_table") {
    throw new Error("Invalid attribution tables.");
  }
  const latency = raw.latency_ms, prices = raw.price_table;
  const nonNegativeInt = (value: unknown): value is number =>
    typeof value === "number" && Number.isInteger(value) && value >= 0;
  if (!isRecord(latency) || Object.keys(latency).length === 0 ||
      Object.entries(latency).some(([key, value]) => !key || !nonNegativeInt(value))) {
    throw new Error("Invalid attribution latency table.");
  }
  if (!isRecord(prices) || Object.keys(prices).length === 0 ||
      Object.entries(prices).some(([key, value]) =>
        !(STEP_KINDS as readonly string[]).includes(key) || !nonNegativeInt(value))) {
    throw new Error("Invalid attribution price table.");
  }
  if ("read" in prices && prices.read !== 0) {
    throw new Error("Attribution reads must price zero.");
  }
  return {latency_ms: {...latency} as Record<string, number>, price_table: {...prices} as Record<string, number>};
}

export function loadScenario(path: string = SCENARIO_PATH): ScenarioDefinition {
  const raw = parse(readFileSync(path, "utf8"));
  if (!isRecord(raw) || raw.schema_version !== "1.0" || raw.scenario_id !== "order-investigation") {
    throw new Error("Unsupported order-investigation scenario document.");
  }
  if (!Array.isArray(raw.cases)) {
    throw new Error("Scenario cases must be an array.");
  }
  const cases = raw.cases.map(parseCase);
  const ids = new Set(cases.map((item) => item.id));
  if (ids.size !== cases.length) {
    throw new Error("Scenario case ids must be unique.");
  }
  return {schema_version: "1.0", scenario_id: "order-investigation", cases, attribution: parseAttribution(raw.attribution)};
}

export function findScenarioCase(scenario: ScenarioDefinition, caseId: string): ScenarioCase {
  const scenarioCase = scenario.cases.find((candidate) => candidate.id === caseId);
  if (scenarioCase === undefined) {
    throw new Error(`Unknown scenario case: ${caseId}`);
  }
  return scenarioCase;
}
