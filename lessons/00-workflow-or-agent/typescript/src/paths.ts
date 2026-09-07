import {fileURLToPath} from "node:url";
import {dirname, resolve} from "node:path";

const CURRENT_DIRECTORY = dirname(fileURLToPath(import.meta.url));

export const REPOSITORY_ROOT = resolve(CURRENT_DIRECTORY, "../../../..");
export const SCENARIO_PATH = resolve(REPOSITORY_ROOT, "fixtures/scenarios/support-triage.yaml");
export const FAKE_MODEL_PATH = resolve(REPOSITORY_ROOT, "fixtures/fake-model/support-triage.yaml");
export const ROUTE_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/routing/route-decision.schema.json");
export const EVENT_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/events/run-event.schema.json");
export const RESULT_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/results/run-result.schema.json");
