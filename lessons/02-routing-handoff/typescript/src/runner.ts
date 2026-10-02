import {randomUUID} from "node:crypto";
import {loadScenario, findScenarioCase, loadFailureFixtures} from "./scenario.js";
import {classifyWithCode, ScriptedRouteProvider} from "./scripted-router.js";
import {applyConfidencePolicy} from "./policy.js";
import {createReceiverDirectory} from "./receivers.js";
import {validateRouteDecision, validateHandoff, validateHandoffResult} from "./schemas.js";
import {MemoryEventSink, writeJsonl} from "./trace.js";
import type {RouterMode, RouteDecisionProvider, ReceiverDirectory, HandoffResult, RouteSelection, FailureCode} from "./types.js";

export interface RunScenarioCaseOptions {
  mode: RouterMode; caseId: string; tracePath: string;
  routeProvider?: RouteDecisionProvider; receiverDirectory?: ReceiverDirectory;
  clock?: () => Date; idFactory?: () => string;
}
export async function runScenarioCase(options: RunScenarioCaseOptions): Promise<HandoffResult> {
  const c = findScenarioCase(loadScenario(), options.caseId);
  if (c.router_mode !== options.mode) throw new Error("Requested mode does not match canonical case mode");
  const nextId = options.idFactory ?? randomUUID;
  const runId = nextId();
  const sink = new MemoryEventSink({runId, source: "typescript", clock: options.clock, idFactory: nextId});
  let selection: RouteSelection | undefined;
  async function finish(failure: FailureCode | null): Promise<HandoffResult> {
    const fields = {proposed_route: selection?.proposedRoute ?? null, selected_route: selection?.selectedRoute ?? null, receiver: selection?.receiver ?? null, fallback_applied: selection?.fallbackApplied ?? false, specialist_invoked: failure === null};
    const result: HandoffResult = {schema_version: "1.0", run_id: runId, scenario_id: "support-handoff", case_id: c.id, router_mode: options.mode, status: failure ? "FAILED" : "SUCCEEDED", ...fields, failure_code: failure, trace_path: options.tracePath};
    const validation = validateHandoffResult(result);
    if (!validation.ok) throw new Error(`Invalid result: ${validation.errors.join("; ")}`);
    sink.emit(failure ? "run.failed" : "run.completed", {status: result.status, ...fields, ...(failure ? {failure_code: failure} : {})});
    await writeJsonl(options.tracePath, sink.events);
    return result;
  }
  sink.emit("run.created", {scenario_id: "support-handoff", case_id: c.id, router_mode: options.mode});
  sink.emit("run.started", {case_id: c.id, router_mode: options.mode});
  let raw: unknown;
  if (options.mode === "code") raw = classifyWithCode(c.request);
  else {
    const provider = options.routeProvider ?? ScriptedRouteProvider.fromFile();
    sink.emit("model.requested", {case_id: c.id});
    raw = await provider.nextDecision({caseId: c.id, request: c.request});
    sink.emit("model.completed", {case_id: c.id, decision: raw});
  }
  const route = validateRouteDecision(raw);
  if (!route.ok) {
    sink.emit("route.rejected", {router_mode: options.mode, failure_code: "INVALID_ROUTE_DECISION"});
    return finish("INVALID_ROUTE_DECISION");
  }
  selection = applyConfidencePolicy(route.value);
  sink.emit("route.selected", {router_mode: options.mode, proposed_route: selection.proposedRoute, selected_route: selection.selectedRoute, confidence: selection.confidence, fallback_applied: selection.fallbackApplied});
  const failure = c.failure_ref ? loadFailureFixtures()[c.failure_ref] : undefined;
  const receiverInput: Record<string, unknown> = {ticket_id: c.ticket_id, request_text: c.request};
  for (const field of failure?.omit_receiver_input_fields ?? []) delete receiverInput[field];
  const candidate = {schema_version: "1.0", handoff_id: nextId(), sender: "support-router", receiver: selection.receiver, sender_intent: {route: selection.proposedRoute, confidence: selection.confidence, policy_outcome: selection.policyOutcome}, receiver_input: receiverInput};
  const {schema_version: _version, ...requestData} = candidate;
  sink.emit("handoff.requested", requestData);
  async function reject(code: FailureCode) {
    sink.emit("handoff.rejected", {handoff_id: candidate.handoff_id, receiver: candidate.receiver, failure_code: code});
    return finish(code);
  }
  const handoff = validateHandoff(candidate);
  if (!handoff.ok) return reject("HANDOFF_CONTEXT_INVALID");
  const directory = options.receiverDirectory ?? createReceiverDirectory(failure?.unavailable_receivers);
  const receiver = directory.resolve(handoff.value.receiver);
  if (!receiver) return reject("HANDOFF_RECEIVER_UNAVAILABLE");
  sink.emit("handoff.accepted", {handoff_id: candidate.handoff_id, receiver: candidate.receiver});
  await receiver.handle(structuredClone(handoff.value.receiver_input));
  return finish(null);
}
