import {readFileSync} from "node:fs";
import {parse} from "yaml";
import {FAKE_MODEL_PATH} from "./paths.js";
import type {RouteDecisionInput, RouteDecisionProvider} from "./types.js";
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
export class ScriptedRouteError extends Error {}
export class ScriptedRouteProvider implements RouteDecisionProvider {
  readonly #decisions: Readonly<Record<string, unknown>>;
  readonly #consumed = new Set<string>();
  constructor(decisions: Record<string, unknown>) { this.#decisions = structuredClone(decisions); }
  static fromFile(path: string = FAKE_MODEL_PATH): ScriptedRouteProvider {
    const raw = parse(readFileSync(path, "utf8"));
    if (!isRecord(raw) || raw.schema_version !== "1.0" || raw.scenario_id !== "support-handoff" || !isRecord(raw.decisions)) {
      throw new ScriptedRouteError("Unsupported M2 scripted route fixture.");
    }
    const decisions: Record<string, unknown> = {};
    for (const [caseId, entry] of Object.entries(raw.decisions)) {
      if (!isRecord(entry) || Object.keys(entry).length !== 1 || !("return" in entry)) throw new ScriptedRouteError(`Decision ${caseId} must contain exactly return.`);
      decisions[caseId] = structuredClone(entry.return);
    }
    return new ScriptedRouteProvider(decisions);
  }
  async nextDecision(input: RouteDecisionInput): Promise<unknown> {
    void input.request;
    if (!(input.caseId in this.#decisions)) throw new ScriptedRouteError(`Missing scripted decision for case: ${input.caseId}`);
    if (this.#consumed.has(input.caseId)) throw new ScriptedRouteError(`Scripted decision already consumed for case: ${input.caseId}`);
    this.#consumed.add(input.caseId);
    return structuredClone(this.#decisions[input.caseId]);
  }
}
export {classifyWithCode} from "./policy.js";
