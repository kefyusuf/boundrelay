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

type JsonValue = string | number | boolean | null | JsonValue[] | {[key: string]: JsonValue};

function jsonSafeValue(value: unknown, seen: WeakSet<object>): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (
    typeof value === "undefined"
    || typeof value === "bigint"
    || typeof value === "symbol"
    || typeof value === "function"
  ) {
    return null;
  }
  if (seen.has(value)) {
    return null;
  }
  seen.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item) => jsonSafeValue(item, seen));
    }
    const prototype = Object.getPrototypeOf(value) as object | null;
    if (prototype !== Object.prototype && prototype !== null) {
      return null;
    }
    const result: {[key: string]: JsonValue} = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = jsonSafeValue(item, seen);
    }
    return result;
  } finally {
    seen.delete(value);
  }
}

function jsonSafeData(data: Record<string, unknown>): Record<string, JsonValue> {
  const value = jsonSafeValue(data, new WeakSet<object>());
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new Error("Event data must be a JSON object");
  }
  return value;
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
    const safeData = jsonSafeData(data);
    this.#sequence += 1;
    const event: RunEvent = {
      schema_version: "1.0",
      event_id: this.#idFactory(),
      run_id: this.#runId,
      sequence: this.#sequence,
      type,
      timestamp: this.#clock().toISOString(),
      source: this.#source,
      data: safeData,
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
