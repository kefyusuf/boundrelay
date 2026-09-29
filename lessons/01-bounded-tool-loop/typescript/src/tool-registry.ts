import {lookupOrder, lookupShipment} from "./fake-tools.js";
import {validateToolArguments} from "./schemas.js";
import type {ToolDefinition, ToolName, ToolRegistry} from "./types.js";

class StaticToolRegistry implements ToolRegistry {
  readonly #definitions: ReadonlyMap<string, ToolDefinition>;

  constructor(definitions: readonly ToolDefinition[]) {
    this.#definitions = new Map(definitions.map((definition) => [definition.name, definition]));
  }

  resolve(name: string): ToolDefinition | undefined {
    return this.#definitions.get(name);
  }
}

function definition(
  name: ToolName,
  invoke: ToolDefinition["invoke"],
): ToolDefinition {
  return Object.freeze({
    name,
    sideEffect: "READ_ONLY" as const,
    timeoutMs: 100,
    validateArguments: (value: unknown) => validateToolArguments(name, value),
    invoke,
  });
}

export function createFakeToolRegistry(): ToolRegistry {
  return new StaticToolRegistry([
    definition("lookup_order", lookupOrder),
    definition("lookup_shipment", lookupShipment),
  ]);
}
