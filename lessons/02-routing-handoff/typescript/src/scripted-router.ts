import {readFileSync} from "node:fs";
import {parse} from "yaml";
import {MODEL_PATH} from "./paths.js";
import {loadScenario} from "./scenario.js";
import type {RouteDecision, RouteDecisionInput, RouteDecisionProvider} from "./types.js";
export function classifyWithCode(request: string): RouteDecision {
  const text = request.toLowerCase();
  const route = ["charged", "charge", "invoice", "payment", "refund", "billed"].some(k => text.includes(k)) ? "billing" : ["error", "crash", "cannot log in", "can't log in", "bug", "broken"].some(k => text.includes(k)) ? "technical" : "general";
  return {route, confidence: 1};
}
export class ScriptedRouteError extends Error {}
export class ScriptedRouteProvider implements RouteDecisionProvider {
  readonly #decisions: Record<string, {return: unknown}>;
  readonly #consumed = new Set<string>();
  constructor(decisions: Record<string, {return: unknown}>) {this.#decisions = structuredClone(decisions);}
  static fromFile(): ScriptedRouteProvider {
    const raw = parse(readFileSync(MODEL_PATH, "utf8"));
    const expected = loadScenario().cases.filter(c => c.router_mode === "model").map(c => c.id).sort();
    if (!raw || raw.schema_version !== "1.0" || raw.scenario_id !== "support-handoff" || !raw.decisions || Object.keys(raw).sort().join() !== "decisions,scenario_id,schema_version" || Object.keys(raw.decisions).sort().join() !== expected.join() || Object.values(raw.decisions).some(v => !v || typeof v !== "object" || Array.isArray(v) || Object.keys(v).join() !== "return")) throw new ScriptedRouteError("Invalid model fixtures");
    return new ScriptedRouteProvider(raw.decisions);
  }
  async nextDecision(input: RouteDecisionInput): Promise<unknown> {
    const record = this.#decisions[input.caseId];
    if (!record || this.#consumed.has(input.caseId)) throw new ScriptedRouteError(`Missing or consumed decision: ${input.caseId}`);
    this.#consumed.add(input.caseId);
    return structuredClone(record.return);
  }
}
