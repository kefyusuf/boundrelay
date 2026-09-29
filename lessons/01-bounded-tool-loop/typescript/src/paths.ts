import {fileURLToPath} from "node:url";
import {dirname, resolve} from "node:path";

const CURRENT_DIRECTORY = dirname(fileURLToPath(import.meta.url));

export const REPOSITORY_ROOT = resolve(CURRENT_DIRECTORY, "../../../..");
export const SCENARIO_PATH = resolve(REPOSITORY_ROOT, "fixtures/scenarios/order-investigation.yaml");
export const FAKE_MODEL_PATH = resolve(REPOSITORY_ROOT, "fixtures/fake-model/order-investigation.yaml");
export const FAKE_TOOLS_PATH = resolve(REPOSITORY_ROOT, "fixtures/fake-tools/order-investigation.yaml");
export const MODEL_TURN_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/agent/model-turn.schema.json");
export const LOOKUP_ORDER_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/tools/lookup-order-arguments.schema.json");
export const LOOKUP_SHIPMENT_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/tools/lookup-shipment-arguments.schema.json");
export const EVENT_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/events/run-event.schema.json");
export const RESULT_SCHEMA_PATH = resolve(REPOSITORY_ROOT, "contracts/results/tool-loop-result.schema.json");
