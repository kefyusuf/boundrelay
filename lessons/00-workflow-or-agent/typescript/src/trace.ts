import {mkdir, writeFile} from "node:fs/promises";
import {dirname} from "node:path";
import {randomUUID} from "node:crypto";

import {validateRunEvent} from "./schemas.js";
import type {EventSource, EventType, RunEvent} from "./types.js";

export interface EventSinkOptions {
  runId: string;
  source: EventSource;
  clock?: (() => Date) | undefined;
  idFactory?: (() => string) | undefined;
}

export class MemoryEventSink {
  readonly #runId: string;
  readonly #source: EventSource;
  readonly #clock: () => Date;
  readonly #idFactory: () => string;
  readonly #events: RunEvent[] = [];
  #sequence = 0;

  constructor(options: EventSinkOptions) {
    this.#runId = options.runId;
    this.#source = options.source;
    this.#clock = options.clock ?? (() => new Date());
    this.#idFactory = options.idFactory ?? randomUUID;
  }

  get events(): readonly RunEvent[] {
    return this.#events.map((event) => structuredClone(event));
  }

  emit(type: EventType, data: Record<string, unknown>): RunEvent {
    this.#sequence += 1;
    const event: RunEvent = {
      schema_version: "1.0",
      event_id: this.#idFactory(),
      run_id: this.#runId,
      sequence: this.#sequence,
      type,
      timestamp: this.#clock().toISOString(),
      source: this.#source,
      data: structuredClone(data),
    };
    const validation = validateRunEvent(event);
    if (!validation.ok) {
      throw new Error(`Invalid run event: ${validation.errors.join("; ")}`);
    }
    const snapshot = Object.freeze(validation.value);
    this.#events.push(snapshot);
    return structuredClone(snapshot);
  }
}

export async function writeJsonl(path: string, events: readonly RunEvent[]): Promise<void> {
  await mkdir(dirname(path), {recursive: true});
  const content = events.map((event) => JSON.stringify(event)).join("\n") + "\n";
  await writeFile(path, content, "utf8");
}
