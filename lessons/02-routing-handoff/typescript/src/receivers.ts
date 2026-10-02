import {ROUTE_RECEIVERS} from "./policy.js";
import type {ReceiverName, ReceiverDirectory, ReceiverDefinition} from "./types.js";
export function createReceiverDirectory(unavailable: readonly ReceiverName[] = []): ReceiverDirectory {
  const definitions = new Map<string, ReceiverDefinition>();
  for (const name of Object.values(ROUTE_RECEIVERS)) if (!unavailable.includes(name)) definitions.set(name, {name, async handle(_input) {}});
  return {resolve: name => definitions.get(name)};
}
