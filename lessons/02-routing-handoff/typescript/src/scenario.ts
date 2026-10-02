import {readFileSync} from "node:fs";
import {parse} from "yaml";
import {SCENARIO_PATH, FAILURE_PATH} from "./paths.js";
import {ROUTE_RECEIVERS} from "./policy.js";
import type {ScenarioDefinition, ScenarioCase, FailureFixtures} from "./types.js";
import Ajv2020 from "ajv/dist/2020.js";
const routes = ["billing", "technical", "general"], receivers = Object.values(ROUTE_RECEIVERS);
const str = {type: "string", minLength: 1}, boolean = {type: "boolean"};
function object(properties: Record<string, unknown>, required = Object.keys(properties)) {return {type: "object", properties, required, additionalProperties: false};}
const header = {schema_version: {const: "1.0"}, scenario_id: {const: "support-handoff"}};
const caseFields = {id: str, ticket_id: {type: "string", pattern: "^TCK-[0-9]{4}$"}, request: str, router_mode: {enum: ["code", "model"]}, expected_status: {enum: ["SUCCEEDED", "FAILED"]}, expected_proposed_route: {enum: routes}, expected_confidence: {type: "number", minimum: 0, maximum: 1}, expected_selected_route: {enum: routes}, expected_receiver: {enum: receivers}, expected_policy_outcome: {enum: ["selected", "fallback"]}, expected_fallback_applied: boolean, expected_specialist_invoked: boolean, expected_failure_code: {enum: [null, "HANDOFF_CONTEXT_INVALID", "HANDOFF_RECEIVER_UNAVAILABLE"]}, failure_ref: str};
const ajv = new Ajv2020({strict: true, allErrors: true});
const scenarioValidator = ajv.compile<ScenarioDefinition>(object({...header, confidence_threshold: {const: 0.8}, route_receivers: object(Object.fromEntries(Object.entries(ROUTE_RECEIVERS).map(([key, value]) => [key, {const: value}]))), cases: {type: "array", minItems: 5, maxItems: 5, items: object(caseFields, Object.keys(caseFields).filter(key => key !== "failure_ref"))}}));
const failureValidator = ajv.compile(object({...header, failures: object({"handoff-context-loss": object({omit_receiver_input_fields: {const: ["request_text"]}}), "handoff-receiver-unavailable": object({unavailable_receivers: {const: ["billing-specialist"]}})})}));
export function loadFailureFixtures(raw: unknown = parse(readFileSync(FAILURE_PATH, "utf8"))): FailureFixtures {
  if (!failureValidator(raw)) throw new Error("Invalid M2 failure fixtures");
  return structuredClone((raw as {failures: FailureFixtures}).failures);
}
export function loadScenario(raw: unknown = parse(readFileSync(SCENARIO_PATH, "utf8"))): ScenarioDefinition {
  if (!scenarioValidator(raw)) throw new Error("Invalid M2 scenario");
  const scenario = structuredClone(raw as ScenarioDefinition);
  const expected = new Set(["code-billing-handoff", "model-technical-handoff", "model-low-confidence-fallback", "handoff-context-loss", "handoff-receiver-unavailable"]);
  for (const c of scenario.cases) {
    if (!expected.delete(c.id)) throw new Error("Duplicate or unknown M2 case");
    const failure = c.id.startsWith("handoff-");
    if (failure ? c.failure_ref !== c.id : c.failure_ref !== undefined) throw new Error("Invalid M2 failure reference");
  }
  return scenario;
}
export function findScenarioCase(scenario: ScenarioDefinition, caseId: string): ScenarioCase {
  const found = scenario.cases.find(c => c.id === caseId);
  if (!found) throw new Error(`Unknown case: ${caseId}`);
  return structuredClone(found);
}
