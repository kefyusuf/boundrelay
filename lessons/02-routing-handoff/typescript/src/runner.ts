import {randomUUID} from "node:crypto";

import {applyConfidencePolicy, classifyWithCode} from "./policy.js";
import {createReceiverDirectory} from "./receivers.js";
import {findScenarioCase, loadFailureFixtures, loadScenario} from "./scenario.js";
import {validateHandoff, validateHandoffResult, validateRouteDecision} from "./schemas.js";
import {ScriptedRouteProvider} from "./scripted-router.js";
import {MemoryEventSink, writeJsonl} from "./trace.js";
import type {
  FailureCode, HandoffResult, ReceiverDirectory, ReceiverInput, ReceiverName,
  Route, RouteDecisionProvider, RouterMode,
} from "./types.js";

export interface RunScenarioCaseOptions {
  mode: RouterMode;
  caseId: string;
  tracePath: string;
  routeProvider?: RouteDecisionProvider | undefined;
  receiverDirectory?: ReceiverDirectory | undefined;
  clock?: (() => Date) | undefined;
  idFactory?: (() => string) | undefined;
}

function observableDecision(raw: unknown): Record<string, unknown> {
  // Validate the original candidate separately; only public routing fields
  // belong in the trace, even when a provider returns private extra fields.
  const value = raw !== null && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
  return {
    route: typeof value.route === "string" && ["billing", "technical", "general"].includes(value.route) ? value.route : null,
    confidence: typeof value.confidence === "number" && Number.isFinite(value.confidence) && value.confidence >= 0 && value.confidence <= 1 ? value.confidence : null,
  };
}

export async function runScenarioCase(options: RunScenarioCaseOptions): Promise<HandoffResult> {
  const scenario = loadScenario();
  const scenarioCase = findScenarioCase(scenario, options.caseId);
  if (scenarioCase.router_mode !== options.mode) throw new Error(`Requested mode ${options.mode} does not match canonical case mode ${scenarioCase.router_mode}.`);

  const idFactory = options.idFactory ?? randomUUID;
  const runId = idFactory();
  const sink = new MemoryEventSink({runId, source:"typescript", clock:options.clock, idFactory});
  const failureFixtures = loadFailureFixtures();
  const directory = options.receiverDirectory ?? createReceiverDirectory();

  let proposedRoute: Route | null = null;
  let selectedRoute: Route | null = null;
  let receiver: ReceiverName | null = null;
  let fallbackApplied = false;
  let specialistInvoked = false;

  sink.emit("run.created", {scenario_id:"support-handoff", case_id:scenarioCase.id, router_mode:options.mode});
  sink.emit("run.started", {case_id:scenarioCase.id, router_mode:options.mode});

  const finishFailure = async (failureCode: FailureCode): Promise<HandoffResult> => {
    sink.emit("run.failed", {
      status:"FAILED", proposed_route:proposedRoute, selected_route:selectedRoute, receiver,
      fallback_applied:fallbackApplied, specialist_invoked:false, failure_code:failureCode,
    });
    const result: HandoffResult = {
      schema_version:"1.0", run_id:runId, scenario_id:"support-handoff", case_id:scenarioCase.id,
      router_mode:options.mode, status:"FAILED", proposed_route:proposedRoute, selected_route:selectedRoute,
      receiver, fallback_applied:fallbackApplied, specialist_invoked:false, failure_code:failureCode,
      trace_path:options.tracePath,
    };
    const validation = validateHandoffResult(result);
    if (!validation.ok) throw new Error(`Invalid handoff result: ${validation.errors.join("; ")}`);
    await writeJsonl(options.tracePath, sink.events);
    return validation.value;
  };

  const finishSuccess = async (): Promise<HandoffResult> => {
    sink.emit("run.completed", {
      status:"SUCCEEDED", proposed_route:proposedRoute, selected_route:selectedRoute, receiver,
      fallback_applied:fallbackApplied, specialist_invoked:true,
    });
    const result: HandoffResult = {
      schema_version:"1.0", run_id:runId, scenario_id:"support-handoff", case_id:scenarioCase.id,
      router_mode:options.mode, status:"SUCCEEDED", proposed_route:proposedRoute, selected_route:selectedRoute,
      receiver, fallback_applied:fallbackApplied, specialist_invoked:true, failure_code:null,
      trace_path:options.tracePath,
    };
    const validation = validateHandoffResult(result);
    if (!validation.ok) throw new Error(`Invalid handoff result: ${validation.errors.join("; ")}`);
    await writeJsonl(options.tracePath, sink.events);
    return validation.value;
  };

  try {
    let rawDecision: unknown;
    if (options.mode === "code") {
      rawDecision = classifyWithCode(scenarioCase.request);
    } else {
      const provider = options.routeProvider ?? ScriptedRouteProvider.fromFile();
      sink.emit("model.requested", {case_id:scenarioCase.id});
      rawDecision = await provider.nextDecision({caseId:scenarioCase.id, request:scenarioCase.request});
      sink.emit("model.completed", {case_id:scenarioCase.id, decision:observableDecision(rawDecision)});
    }

    const decisionValidation = validateRouteDecision(rawDecision);
    if (!decisionValidation.ok) {
      sink.emit("route.rejected", {router_mode:options.mode, failure_code:"INVALID_ROUTE_DECISION"});
      return await finishFailure("INVALID_ROUTE_DECISION");
    }

    const selection = applyConfidencePolicy(decisionValidation.value);
    proposedRoute = selection.proposedRoute;
    selectedRoute = selection.selectedRoute;
    receiver = selection.receiver;
    fallbackApplied = selection.fallbackApplied;
    sink.emit("route.selected", {
      router_mode:options.mode, proposed_route:selection.proposedRoute, selected_route:selection.selectedRoute,
      confidence:selection.confidence, fallback_applied:selection.fallbackApplied,
    });

    const receiverInput: Record<string, unknown> = {ticket_id:scenarioCase.ticket_id, request_text:scenarioCase.request};
    const failure = scenarioCase.failure_ref === undefined ? undefined : failureFixtures[scenarioCase.failure_ref];
    if (failure !== undefined && "omit_receiver_input_fields" in failure) {
      for (const field of failure.omit_receiver_input_fields) delete receiverInput[field];
    }
    const handoffId = idFactory();
    const candidate = {
      schema_version:"1.0", handoff_id:handoffId, sender:"support-router", receiver:selection.receiver,
      sender_intent:{route:selection.proposedRoute, confidence:selection.confidence, policy_outcome:selection.policyOutcome},
      receiver_input:receiverInput,
    };
    sink.emit("handoff.requested", {
      handoff_id:handoffId, sender:"support-router", receiver:selection.receiver,
      sender_intent:candidate.sender_intent, receiver_input:candidate.receiver_input,
    });

    const handoffValidation = validateHandoff(candidate);
    if (!handoffValidation.ok) {
      sink.emit("handoff.rejected", {handoff_id:handoffId, receiver:selection.receiver, failure_code:"HANDOFF_CONTEXT_INVALID"});
      return await finishFailure("HANDOFF_CONTEXT_INVALID");
    }

    const unavailable = failure !== undefined && "unavailable_receivers" in failure && failure.unavailable_receivers.includes(selection.receiver);
    const definition = unavailable ? undefined : directory.resolve(selection.receiver);
    if (definition === undefined) {
      sink.emit("handoff.rejected", {handoff_id:handoffId, receiver:selection.receiver, failure_code:"HANDOFF_RECEIVER_UNAVAILABLE"});
      return await finishFailure("HANDOFF_RECEIVER_UNAVAILABLE");
    }

    sink.emit("handoff.accepted", {handoff_id:handoffId, receiver:selection.receiver});
    await definition.handle(structuredClone(handoffValidation.value.receiver_input) as ReceiverInput);
    specialistInvoked = true;
    return await finishSuccess();
  } catch (error: unknown) {
    await writeJsonl(options.tracePath, sink.events);
    throw error;
  }
}
