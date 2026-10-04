import {readFileSync} from "node:fs";
import {parse} from "yaml";
import {FAILURES_PATH, SCENARIO_PATH} from "./paths.js";
import {
  FAILURE_CODES, RECEIVER_NAMES, ROUTES,
  type FailureCode, type FailureFixture, type FailureFixtures,
  type PolicyOutcome, type ReceiverInputField, type ReceiverName,
  type Route, type RouterMode, type RunStatus, type ScenarioCase, type ScenarioDefinition,
} from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) throw new Error(`${key} must be a non-empty string.`);
  return value;
}
function requireNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${key} must be a finite number.`);
  return value;
}
function requireBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") throw new Error(`${key} must be a boolean.`);
  return value;
}
function enumValue<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) throw new Error(`${label} is unsupported.`);
  return value as T;
}
function exactKeys(record: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const extras = Object.keys(record).filter((key) => !allowed.includes(key));
  if (extras.length) throw new Error(`${label} has unsupported field: ${extras[0]}`);
}

export function loadFailureFixtures(path: unknown = FAILURES_PATH): FailureFixtures {
  const raw = typeof path === "string" ? parse(readFileSync(path, "utf8")) : path;
  if (!isRecord(raw) || raw.schema_version !== "1.0" || raw.scenario_id !== "support-handoff" || !isRecord(raw.failures)) {
    throw new Error("Unsupported support-handoff failure fixture.");
  }
  const result: FailureFixtures = {};
  for (const [caseId, value] of Object.entries(raw.failures)) {
    if (!isRecord(value)) throw new Error(`${caseId} failure fixture must be an object.`);
    const keys = Object.keys(value);
    if (keys.length !== 1 || (keys[0] !== "omit_receiver_input_fields" && keys[0] !== "unavailable_receivers")) {
      throw new Error(`${caseId} has unsupported failure operator.`);
    }
    if (caseId.startsWith("code-") || caseId.startsWith("model-")) throw new Error(`${caseId} success case cannot define failure operators.`);
    if (keys[0] === "omit_receiver_input_fields") {
      const fields = value.omit_receiver_input_fields;
      if (!Array.isArray(fields) || fields.length === 0 || fields.some((x) => x !== "ticket_id" && x !== "request_text")) {
        throw new Error(`${caseId} omit_receiver_input_fields is invalid.`);
      }
      result[caseId] = {omit_receiver_input_fields: [...fields] as ReceiverInputField[]};
    } else {
      const receivers = value.unavailable_receivers;
      if (!Array.isArray(receivers) || receivers.length === 0 || receivers.some((x) => typeof x !== "string" || !(RECEIVER_NAMES as readonly string[]).includes(x))) {
        throw new Error(`${caseId} unavailable_receivers is invalid.`);
      }
      result[caseId] = {unavailable_receivers: [...receivers] as ReceiverName[]};
    }
  }
  return result;
}

function parseCase(raw: unknown, failures: FailureFixtures): ScenarioCase {
  if (!isRecord(raw)) throw new Error("Scenario case must be an object.");
  const allowed = ["id","ticket_id","request","router_mode","expected_status","expected_proposed_route","expected_confidence","expected_selected_route","expected_receiver","expected_policy_outcome","expected_fallback_applied","expected_specialist_invoked","expected_failure_code","failure_ref"];
  exactKeys(raw, allowed, requireString(raw, "id"));
  const expectedStatus = enumValue<RunStatus>(raw.expected_status, ["SUCCEEDED","FAILED"], "expected_status");
  const item: ScenarioCase = {
    id: requireString(raw, "id"), ticket_id: requireString(raw, "ticket_id"), request: requireString(raw, "request"),
    router_mode: enumValue<RouterMode>(raw.router_mode, ["code","model"], "router_mode"),
    expected_status: expectedStatus,
    expected_proposed_route: enumValue<Route>(raw.expected_proposed_route, ROUTES, "expected_proposed_route"),
    expected_confidence: requireNumber(raw, "expected_confidence"),
    expected_selected_route: enumValue<Route>(raw.expected_selected_route, ROUTES, "expected_selected_route"),
    expected_receiver: enumValue<ReceiverName>(raw.expected_receiver, RECEIVER_NAMES, "expected_receiver"),
    expected_policy_outcome: enumValue<PolicyOutcome>(raw.expected_policy_outcome, ["selected","fallback"], "expected_policy_outcome"),
    expected_fallback_applied: requireBoolean(raw, "expected_fallback_applied"),
    expected_specialist_invoked: requireBoolean(raw, "expected_specialist_invoked"),
  };
  if (!/^TCK-[0-9]{4}$/.test(item.ticket_id)) throw new Error(`${item.id} ticket_id is invalid.`);
  if (item.expected_confidence < 0 || item.expected_confidence > 1) throw new Error(`${item.id} expected_confidence must be between 0 and 1.`);
  if (expectedStatus === "SUCCEEDED") {
    if (raw.expected_failure_code !== undefined || raw.failure_ref !== undefined) throw new Error(`${item.id} success case cannot define failure fields.`);
    return item;
  }
  item.expected_failure_code = enumValue<FailureCode>(raw.expected_failure_code, FAILURE_CODES, "expected_failure_code");
  const failureRef = requireString(raw, "failure_ref");
  if (failures[failureRef] === undefined) throw new Error(`Unknown failure_ref: ${failureRef}`);
  item.failure_ref = failureRef;
  return item;
}

export function loadScenario(path: unknown = SCENARIO_PATH, failurePath: string = FAILURES_PATH): ScenarioDefinition {
  const failures = loadFailureFixtures(failurePath);
  const raw = typeof path === "string" ? parse(readFileSync(path, "utf8")) : path;
  if (!isRecord(raw) || raw.schema_version !== "1.0" || raw.scenario_id !== "support-handoff") throw new Error("Unsupported support-handoff scenario document.");
  if (typeof raw.confidence_threshold !== "number" || !Number.isFinite(raw.confidence_threshold)) throw new Error("confidence_threshold must be a finite number.");
  if (raw.confidence_threshold !== 0.80) throw new Error("confidence_threshold must be 0.80.");
  if (!isRecord(raw.route_receivers)) throw new Error("route_receivers must be an object.");
  const expectedMapping: Record<Route, ReceiverName> = {billing:"billing-specialist", technical:"technical-specialist", general:"general-specialist"};
  exactKeys(raw.route_receivers, ROUTES, "route_receivers");
  for (const route of ROUTES) {
    if (raw.route_receivers[route] !== expectedMapping[route]) throw new Error(`route_receivers.${route} must be ${expectedMapping[route]}.`);
  }
  if (!Array.isArray(raw.cases)) throw new Error("Scenario cases must be an array.");
  const cases = raw.cases.map((item) => parseCase(item, failures));
  const ids = new Set(cases.map((item) => item.id));
  if (ids.size !== cases.length) throw new Error("Scenario case ids must be unique.");
  const expectedIds = ["code-billing-handoff", "model-technical-handoff", "model-low-confidence-fallback", "handoff-context-loss", "handoff-receiver-unavailable"];
  if (ids.size !== expectedIds.length || expectedIds.some((id) => !ids.has(id))) throw new Error("Scenario must contain exactly the five canonical M2 cases.");
  for (const item of cases) {
    const expectedRef = item.id.startsWith("handoff-") ? item.id : undefined;
    if (item.failure_ref !== expectedRef) throw new Error(`${item.id} has an invalid M2 failure reference.`);
  }
  return {schema_version:"1.0", scenario_id:"support-handoff", confidence_threshold:raw.confidence_threshold, route_receivers:expectedMapping, cases};
}
export function findScenarioCase(scenario: ScenarioDefinition, caseId: string): ScenarioCase {
  const item = scenario.cases.find((candidate) => candidate.id === caseId);
  if (item === undefined) throw new Error(`Unknown scenario case: ${caseId}`);
  return item;
}
