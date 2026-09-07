import {readFileSync} from "node:fs";

import {parse} from "yaml";

import {FAKE_MODEL_PATH} from "./paths.js";
import type {DecisionProvider} from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class ScriptedDecisionProvider implements DecisionProvider {
  readonly #responses: Readonly<Record<string, unknown>>;

  constructor(responses: Record<string, unknown>) {
    this.#responses = structuredClone(responses);
  }

  static fromFile(path: string = FAKE_MODEL_PATH): ScriptedDecisionProvider {
    const document = parse(readFileSync(path, "utf8"));
    if (!isRecord(document) || document.schema_version !== "1.0" || document.scenario_id !== "support-triage") {
      throw new Error("Unsupported scripted decision fixture.");
    }
    if (!isRecord(document.responses)) {
      throw new Error("Scripted decision fixture must contain a responses object.");
    }

    const responses: Record<string, unknown> = {};
    for (const [caseId, entry] of Object.entries(document.responses)) {
      if (!isRecord(entry) || !("return" in entry)) {
        throw new Error(`Scripted response ${caseId} must contain a return value.`);
      }
      responses[caseId] = structuredClone(entry.return);
    }
    return new ScriptedDecisionProvider(responses);
  }

  async classify(input: {caseId: string; request: string}): Promise<unknown> {
    void input.request;
    if (!(input.caseId in this.#responses)) {
      throw new Error(`Missing scripted decision for case: ${input.caseId}`);
    }
    return structuredClone(this.#responses[input.caseId]);
  }
}
