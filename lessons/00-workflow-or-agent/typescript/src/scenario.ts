import {readFileSync} from "node:fs";

import {parse} from "yaml";

import {SCENARIO_PATH} from "./paths.js";
import {STEP_KINDS, type AttributionTables} from "./attribution.js";
import {ROUTES, type FailureCode, type Route, type ScenarioCase, type ScenarioDefinition} from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

export function parseAttribution(raw: unknown): AttributionTables | null {
  if (raw === undefined || raw === null) {
    return null;
  }
  if (!isRecord(raw) || Object.keys(raw).sort().join("|") !== "latency_ms|price_table") {
    throw new Error("Invalid attribution tables.");
  }
  const latency = raw.latency_ms, prices = raw.price_table;
  if (!isRecord(latency) || Object.keys(latency).length === 0 ||
      Object.entries(latency).some(([key, value]) => !key || !isNonNegativeInt(value))) {
    throw new Error("Invalid attribution latency table.");
  }
  if (!isRecord(prices) || Object.keys(prices).length === 0 ||
      Object.entries(prices).some(([key, value]) =>
        !(STEP_KINDS as readonly string[]).includes(key) || !isNonNegativeInt(value))) {
    throw new Error("Invalid attribution price table.");
  }
  if ("read" in prices && prices.read !== 0) {
    throw new Error("Attribution reads must price zero.");
  }
  return {latency_ms: {...latency} as Record<string, number>, price_table: {...prices} as Record<string, number>};
}

function isRoute(value: unknown): value is Route {
  return typeof value === "string" && (ROUTES as readonly string[]).includes(value);
}

function parseCase(raw: unknown): ScenarioCase {
  if (!isRecord(raw) || typeof raw.id !== "string" || typeof raw.request !== "string") {
    throw new Error("Scenario case must define string id and request fields.");
  }

  if (isRoute(raw.expected_route) && raw.expected_failure_code === undefined) {
    return {id: raw.id, request: raw.request, expected_route: raw.expected_route};
  }

  if (raw.expected_route === undefined && raw.expected_failure_code === "INVALID_ROUTE_DECISION") {
    return {
      id: raw.id,
      request: raw.request,
      expected_failure_code: raw.expected_failure_code as FailureCode,
    };
  }

  throw new Error(`Scenario case ${raw.id} must define exactly one supported expectation.`);
}

export function loadScenario(path: string = SCENARIO_PATH): ScenarioDefinition {
  const raw = parse(readFileSync(path, "utf8"));
  if (!isRecord(raw) || raw.schema_version !== "1.0" || raw.scenario_id !== "support-triage") {
    throw new Error("Unsupported support-triage scenario document.");
  }
  const hasCanonicalRoutes =
    Array.isArray(raw.routes) &&
    raw.routes.length === ROUTES.length &&
    raw.routes.every((route, index) => route === ROUTES[index]);
  if (!hasCanonicalRoutes) {
    throw new Error("Scenario routes must match the canonical M0 routes.");
  }
  if (!Array.isArray(raw.cases)) {
    throw new Error("Scenario cases must be an array.");
  }

  return {
    schema_version: "1.0",
    scenario_id: "support-triage",
    routes: [...ROUTES],
    cases: raw.cases.map(parseCase),
    attribution: parseAttribution(raw.attribution),
  };
}

export function findScenarioCase(scenario: ScenarioDefinition, caseId: string): ScenarioCase {
  const scenarioCase = scenario.cases.find((candidate) => candidate.id === caseId);
  if (scenarioCase === undefined) {
    throw new Error(`Unknown scenario case: ${caseId}`);
  }
  return scenarioCase;
}
