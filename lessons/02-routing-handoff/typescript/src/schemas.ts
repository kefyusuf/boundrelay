import {readFileSync} from "node:fs";
import Ajv2020, {type ValidateFunction} from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import {EVENT_SCHEMA_PATH, RESULT_SCHEMA_PATH, HANDOFF_SCHEMA_PATH, ROUTE_SCHEMA_PATH} from "./paths.js";
import type {RunEvent, HandoffResult, HandoffEnvelope, RouteDecision, ValidationResult} from "./types.js";
const ajv = new Ajv2020({strict: true, allErrors: true});
addFormats(ajv);
function compile<T>(path: string): ValidateFunction<T> {return ajv.compile<T>(JSON.parse(readFileSync(path, "utf8")));}
function validate<T>(schema: ValidateFunction<T>, value: unknown): ValidationResult<T> {
  return schema(value) ? {ok: true, value: structuredClone(value)} : {ok: false, errors: (schema.errors ?? []).map(e => `${e.instancePath || "/"} ${e.message}`)};
}
const route = compile<RouteDecision>(ROUTE_SCHEMA_PATH), handoff = compile<HandoffEnvelope>(HANDOFF_SCHEMA_PATH), event = compile<RunEvent>(EVENT_SCHEMA_PATH), result = compile<HandoffResult>(RESULT_SCHEMA_PATH);
export const validateRouteDecision = (value: unknown) => validate(route, value);
export const validateHandoff = (value: unknown) => validate(handoff, value);
export const validateRunEvent = (value: unknown) => validate(event, value);
export const validateHandoffResult = (value: unknown) => validate(result, value);
