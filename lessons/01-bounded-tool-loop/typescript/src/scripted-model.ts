import {readFileSync} from "node:fs";

import {parse} from "yaml";

import {FAKE_MODEL_PATH} from "./paths.js";
import type {ModelInput, ModelProvider} from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class ScriptedModelError extends Error {}

export class ScriptedModelProvider implements ModelProvider {
  readonly #trajectories: Readonly<Record<string, readonly unknown[]>>;
  readonly #nextSteps = new Map<string, number>();

  constructor(trajectories: Record<string, readonly unknown[]>) {
    this.#trajectories = structuredClone(trajectories);
  }

  static fromFile(path: string = FAKE_MODEL_PATH): ScriptedModelProvider {
    const document = parse(readFileSync(path, "utf8"));
    if (!isRecord(document) || document.schema_version !== "1.0" || document.scenario_id !== "order-investigation") {
      throw new ScriptedModelError("Unsupported M1 scripted model fixture.");
    }
    if (!isRecord(document.trajectories)) {
      throw new ScriptedModelError("Scripted model fixture must contain trajectories.");
    }
    const trajectories: Record<string, readonly unknown[]> = {};
    for (const [caseId, rawTurns] of Object.entries(document.trajectories)) {
      if (!Array.isArray(rawTurns) || rawTurns.length === 0) {
        throw new ScriptedModelError(`Trajectory ${caseId} must be a non-empty array.`);
      }
      trajectories[caseId] = rawTurns.map((entry) => {
        if (!isRecord(entry) || !("return" in entry)) {
          throw new ScriptedModelError(`Trajectory ${caseId} entries must contain return values.`);
        }
        return structuredClone(entry.return);
      });
    }
    return new ScriptedModelProvider(trajectories);
  }

  async nextTurn(input: ModelInput): Promise<unknown> {
    void input.request;
    void input.observations;
    const trajectory = this.#trajectories[input.caseId];
    if (trajectory === undefined) {
      throw new ScriptedModelError(`Missing scripted trajectory for case: ${input.caseId}`);
    }
    const expectedStep = this.#nextSteps.get(input.caseId) ?? 1;
    if (input.modelStep !== expectedStep) {
      throw new ScriptedModelError(
        `Out-of-order scripted turn for ${input.caseId}: expected ${expectedStep}, got ${input.modelStep}.`,
      );
    }
    const value = trajectory[input.modelStep - 1];
    if (value === undefined) {
      throw new ScriptedModelError(`Scripted trajectory exhausted for ${input.caseId} at step ${input.modelStep}.`);
    }
    this.#nextSteps.set(input.caseId, expectedStep + 1);
    return structuredClone(value);
  }
}
