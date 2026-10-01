import {RECEIVER_NAMES, type ReceiverDefinition, type ReceiverDirectory, type ReceiverInput, type ReceiverName} from "./types.js";
class StaticReceiverDirectory implements ReceiverDirectory {
  readonly #definitions: ReadonlyMap<string, ReceiverDefinition>;
  constructor(definitions: readonly ReceiverDefinition[]) { this.#definitions = new Map(definitions.map((d) => [d.name,d])); }
  resolve(name: string): ReceiverDefinition | undefined { return this.#definitions.get(name); }
}
function receiver(name: ReceiverName): ReceiverDefinition {
  return Object.freeze({
    name,
    async handle(input: ReceiverInput): Promise<void> { void input.ticket_id; void input.request_text; },
  });
}
export function createReceiverDirectory(unavailable: readonly ReceiverName[] = []): ReceiverDirectory {
  const unavailableSet = new Set<ReceiverName>(unavailable);
  return new StaticReceiverDirectory(RECEIVER_NAMES.filter((name) => !unavailableSet.has(name)).map(receiver));
}
