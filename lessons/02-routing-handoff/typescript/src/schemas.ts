import {readFileSync} from "node:fs";
import Ajv2020, {type ErrorObject, type ValidateFunction} from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import {EVENT_SCHEMA_PATH, HANDOFF_SCHEMA_PATH, RESULT_SCHEMA_PATH, ROUTE_SCHEMA_PATH} from "./paths.js";
import type {HandoffEnvelope, HandoffResult, RouteDecision, RunEvent, ValidationResult} from "./types.js";

function loadSchema(path: string): object {
  return JSON.parse(readFileSync(path, "utf8")) as object;
}
const ajv = new Ajv2020({allErrors: true, strict: true});
addFormats(ajv);
const routeValidator = ajv.compile<RouteDecision>(loadSchema(ROUTE_SCHEMA_PATH));
const handoffValidator = ajv.compile<HandoffEnvelope>(loadSchema(HANDOFF_SCHEMA_PATH));
const eventValidator = ajv.compile<RunEvent>(loadSchema(EVENT_SCHEMA_PATH));
const resultValidator = ajv.compile<HandoffResult>(loadSchema(RESULT_SCHEMA_PATH));
function stableErrors(errors: ErrorObject[] | null | undefined): string[] {
  return (errors ?? []).map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`);
}
function validate<T>(validator: ValidateFunction<T>, raw: unknown): ValidationResult<T> {
  if (validator(raw)) return {ok: true, value: structuredClone(raw)};
  return {ok: false, errors: stableErrors(validator.errors)};
}
export function validateRouteDecision(raw: unknown): ValidationResult<RouteDecision> { return validate(routeValidator, raw); }
export function validateHandoff(raw: unknown): ValidationResult<HandoffEnvelope> { return validate(handoffValidator, raw); }
export function validateRunEvent(raw: unknown): ValidationResult<RunEvent> { return validate(eventValidator, raw); }
export function validateHandoffResult(raw: unknown): ValidationResult<HandoffResult> { return validate(resultValidator, raw); }
