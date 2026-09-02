import {randomUUID} from "node:crypto";

import {routeDecision} from "./bounded-router.js";
import {classifyDeterministically} from "./deterministic-router.js";
import {ScriptedDecisionProvider} from "./fake-decision-provider.js";
import {findScenarioCase, loadScenario} from "./scenario.js";
import {validateRunResult} from "./schemas.js";
import {RecordingSpecialistDispatcher} from "./specialists.js";
import {MemoryEventSink, writeJsonl} from "./trace.js";
import type {DecisionProvider, RunMode, RunResult, SpecialistDispatcher} from "./types.js";

export interface RunScenarioCaseOptions {
  mode: RunMode;
  caseId: string;
  tracePath: string;
  decisionProvider?: DecisionProvider | undefined;
  specialistDispatcher?: SpecialistDispatcher | undefined;
  clock?: (() => Date) | undefined;
  idFactory?: (() => string) | undefined;
}

export async function runScenarioCase(options: RunScenarioCaseOptions): Promise<RunResult> {
  const scenario = loadScenario();
  const scenarioCase = findScenarioCase(scenario, options.caseId);
  const idFactory = options.idFactory ?? randomUUID;
  const runId = idFactory();
  const sink = new MemoryEventSink({
    runId,
    source: "typescript",
    clock: options.clock,
    idFactory,
  });
  const dispatcher = options.specialistDispatcher ?? new RecordingSpecialistDispatcher();

  sink.emit("run.created", {
    scenario_id: scenario.scenario_id,
    case_id: scenarioCase.id,
    mode: options.mode,
  });
  sink.emit("run.started", {case_id: scenarioCase.id, mode: options.mode});
  sink.emit("step.started", {step: "classify"});

  let rawDecision: unknown;
  if (options.mode === "deterministic") {
    rawDecision = classifyDeterministically(scenarioCase.request);
  } else {
    const provider = options.decisionProvider ?? ScriptedDecisionProvider.fromFile();
    sink.emit("model.requested", {case_id: scenarioCase.id});
    rawDecision = await provider.classify({caseId: scenarioCase.id, request: scenarioCase.request});
    sink.emit("model.completed", {case_id: scenarioCase.id, decision: structuredClone(rawDecision)});
  }

  const routed = routeDecision(rawDecision);
  if (!routed.ok) {
    sink.emit("route.rejected", {
      route: routed.rejectedRoute,
      failure_code: routed.failureCode,
    });
    sink.emit("step.failed", {step: "classify", failure_code: routed.failureCode});
    sink.emit("run.failed", {status: "FAILED", failure_code: routed.failureCode});

    const result: RunResult = {
      schema_version: "1.0",
      run_id: runId,
      scenario_id: "support-triage",
      case_id: scenarioCase.id,
      mode: options.mode,
      status: "FAILED",
      selected_route: null,
      specialist_invoked: false,
      failure_code: routed.failureCode,
      trace_path: options.tracePath,
    };
    const validation = validateRunResult(result);
    if (!validation.ok) {
      throw new Error(`Invalid run result: ${validation.errors.join("; ")}`);
    }
    await writeJsonl(options.tracePath, sink.events);
    return validation.value;
  }

  const {decision} = routed;
  sink.emit("route.selected", {route: decision.route, confidence: decision.confidence});
  sink.emit("step.completed", {step: "classify", route: decision.route});
  const specialistStep = `specialist.${decision.route}`;
  sink.emit("step.started", {step: specialistStep, route: decision.route});
  await dispatcher.dispatch({route: decision.route, request: scenarioCase.request});
  sink.emit("step.completed", {step: specialistStep, route: decision.route});
  sink.emit("run.completed", {status: "SUCCEEDED", route: decision.route});

  const result: RunResult = {
    schema_version: "1.0",
    run_id: runId,
    scenario_id: "support-triage",
    case_id: scenarioCase.id,
    mode: options.mode,
    status: "SUCCEEDED",
    selected_route: decision.route,
    specialist_invoked: true,
    failure_code: null,
    trace_path: options.tracePath,
  };
  const validation = validateRunResult(result);
  if (!validation.ok) {
    throw new Error(`Invalid run result: ${validation.errors.join("; ")}`);
  }
  await writeJsonl(options.tracePath, sink.events);
  return validation.value;
}
