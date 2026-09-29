import {randomUUID} from "node:crypto";

import {ToolExecutionError, ToolTimeoutError, invokeTool} from "./executor.js";
import {findScenarioCase, loadScenario} from "./scenario.js";
import {validateModelTurn, validateRunResult} from "./schemas.js";
import {ScriptedModelProvider} from "./scripted-model.js";
import {createFakeToolRegistry} from "./tool-registry.js";
import {MemoryEventSink, writeJsonl} from "./trace.js";
import type {
  FailureCode,
  ModelProvider,
  RunMode,
  RunResult,
  ScenarioCase,
  ToolObservation,
  ToolRegistry,
} from "./types.js";

export interface RunScenarioCaseOptions {
  mode: RunMode;
  caseId: string;
  tracePath: string;
  modelProvider?: ModelProvider | undefined;
  toolRegistry?: ToolRegistry | undefined;
  clock?: (() => Date) | undefined;
  idFactory?: (() => string) | undefined;
}

export async function runScenarioCase(options: RunScenarioCaseOptions): Promise<RunResult> {
  const scenario = loadScenario();
  const scenarioCase = findScenarioCase(scenario, options.caseId);
  if (scenarioCase.mode !== options.mode) {
    throw new Error(`Requested mode ${options.mode} does not match canonical case mode ${scenarioCase.mode}.`);
  }

  const idFactory = options.idFactory ?? randomUUID;
  const runId = idFactory();
  const sink = new MemoryEventSink({runId, source: "typescript", clock: options.clock, idFactory});
  const registry = options.toolRegistry ?? createFakeToolRegistry();
  let modelSteps = 0;
  let tokensUsed = 0;
  let toolInvocations = 0;

  sink.emit("run.created", {scenario_id: scenario.scenario_id, case_id: scenarioCase.id, mode: options.mode});
  sink.emit("run.started", {case_id: scenarioCase.id, mode: options.mode});

  const finishFailure = async (failureCode: FailureCode): Promise<RunResult> => {
    sink.emit("run.failed", {
      status: "FAILED",
      failure_code: failureCode,
      model_steps: modelSteps,
      tokens_used: tokensUsed,
      tool_invocations: toolInvocations,
    });
    const result: RunResult = {
      schema_version: "1.0",
      run_id: runId,
      scenario_id: "order-investigation",
      case_id: scenarioCase.id,
      mode: options.mode,
      status: "FAILED",
      answer: null,
      failure_code: failureCode,
      model_steps: modelSteps,
      tokens_used: tokensUsed,
      tool_invocations: toolInvocations,
      trace_path: options.tracePath,
    };
    const validation = validateRunResult(result);
    if (!validation.ok) throw new Error(`Invalid run result: ${validation.errors.join("; ")}`);
    await writeJsonl(options.tracePath, sink.events);
    return validation.value;
  };

  const finishSuccess = async (answer: string): Promise<RunResult> => {
    sink.emit("run.completed", {
      status: "SUCCEEDED",
      answer,
      model_steps: modelSteps,
      tokens_used: tokensUsed,
      tool_invocations: toolInvocations,
    });
    const result: RunResult = {
      schema_version: "1.0",
      run_id: runId,
      scenario_id: "order-investigation",
      case_id: scenarioCase.id,
      mode: options.mode,
      status: "SUCCEEDED",
      answer,
      failure_code: null,
      model_steps: modelSteps,
      tokens_used: tokensUsed,
      tool_invocations: toolInvocations,
      trace_path: options.tracePath,
    };
    const validation = validateRunResult(result);
    if (!validation.ok) throw new Error(`Invalid run result: ${validation.errors.join("; ")}`);
    await writeJsonl(options.tracePath, sink.events);
    return validation.value;
  };

  if (options.mode === "direct") {
    if (scenarioCase.expected_status !== "SUCCEEDED" || scenarioCase.direct_call === undefined) {
      throw new Error(`Direct case ${scenarioCase.id} must define a direct call.`);
    }
    const call = scenarioCase.direct_call;
    const definition = registry.resolve(call.tool);
    if (definition === undefined) return finishFailure("UNKNOWN_TOOL");
    const argumentsValidation = definition.validateArguments(call.arguments);
    if (!argumentsValidation.ok) return finishFailure("INVALID_TOOL_ARGUMENTS");
    sink.emit("tool.requested", {call_id: call.call_id, tool: call.tool, arguments: argumentsValidation.value});
    toolInvocations += 1;
    try {
      const output = await invokeTool(definition, argumentsValidation.value);
      const observation: ToolObservation = {call_id: call.call_id, tool: definition.name, output};
      sink.emit("tool.completed", {call_id: call.call_id, tool: definition.name, observation});
      const orderId = output.order_id;
      const status = output.status;
      if (typeof orderId !== "string" || typeof status !== "string") throw new ToolExecutionError(definition.name, "lookup_order returned an invalid observation.");
      return finishSuccess(`Order ${orderId} status is ${status}.`);
    } catch (error: unknown) {
      const failureCode: FailureCode = error instanceof ToolTimeoutError ? "TOOL_TIMEOUT" : "TOOL_EXECUTION_FAILED";
      sink.emit("tool.failed", {call_id: call.call_id, tool: definition.name, failure_code: failureCode});
      return finishFailure(failureCode);
    }
  }

  const provider = options.modelProvider ?? ScriptedModelProvider.fromFile();
  const observations: ToolObservation[] = [];

  while (true) {
    if (modelSteps >= scenarioCase.max_steps) {
      sink.emit("budget.exceeded", {budget: "step", consumed: modelSteps, limit: scenarioCase.max_steps, failure_code: "STEP_BUDGET_EXCEEDED"});
      return finishFailure("STEP_BUDGET_EXCEEDED");
    }

    const modelStep = modelSteps + 1;
    sink.emit("model.requested", {case_id: scenarioCase.id, model_step: modelStep});
    modelSteps = modelStep;

    let rawTurn: unknown;
    try {
      rawTurn = await provider.nextTurn({
        caseId: scenarioCase.id,
        request: scenarioCase.request,
        modelStep,
        observations: structuredClone(observations),
      });
    } catch (_error: unknown) {
      sink.emit("model.failed", {case_id: scenarioCase.id, model_step: modelStep, failure_code: "INVALID_MODEL_DECISION"});
      return finishFailure("INVALID_MODEL_DECISION");
    }

    sink.emit("model.completed", {case_id: scenarioCase.id, model_step: modelStep, turn: rawTurn});
    const turnValidation = validateModelTurn(rawTurn);
    if (!turnValidation.ok) return finishFailure("INVALID_MODEL_DECISION");
    const turn = turnValidation.value;

    tokensUsed += turn.usage.input_tokens + turn.usage.output_tokens;
    sink.emit("budget.consumed", {
      model_steps: modelSteps,
      max_steps: scenarioCase.max_steps,
      tokens_used: tokensUsed,
      max_tokens: scenarioCase.max_tokens,
    });

    if (tokensUsed > scenarioCase.max_tokens) {
      sink.emit("budget.exceeded", {budget: "token", consumed: tokensUsed, limit: scenarioCase.max_tokens, failure_code: "TOKEN_BUDGET_EXCEEDED"});
      return finishFailure("TOKEN_BUDGET_EXCEEDED");
    }

    if (turn.decision.kind === "final") return finishSuccess(turn.decision.answer);

    const definition = registry.resolve(turn.decision.tool);
    if (definition === undefined) return finishFailure("UNKNOWN_TOOL");
    const argumentsValidation = definition.validateArguments(turn.decision.arguments);
    if (!argumentsValidation.ok) return finishFailure("INVALID_TOOL_ARGUMENTS");

    if (modelSteps >= scenarioCase.max_steps) {
      sink.emit("budget.exceeded", {budget: "step", consumed: modelSteps, limit: scenarioCase.max_steps, failure_code: "STEP_BUDGET_EXCEEDED"});
      return finishFailure("STEP_BUDGET_EXCEEDED");
    }

    sink.emit("tool.requested", {call_id: turn.decision.call_id, tool: definition.name, arguments: argumentsValidation.value});
    toolInvocations += 1;
    try {
      const output = await invokeTool(definition, argumentsValidation.value);
      const observation: ToolObservation = {call_id: turn.decision.call_id, tool: definition.name, output};
      sink.emit("tool.completed", {call_id: turn.decision.call_id, tool: definition.name, observation});
      observations.push(observation);
    } catch (error: unknown) {
      const failureCode: FailureCode = error instanceof ToolTimeoutError ? "TOOL_TIMEOUT" : "TOOL_EXECUTION_FAILED";
      sink.emit("tool.failed", {call_id: turn.decision.call_id, tool: definition.name, failure_code: failureCode});
      return finishFailure(failureCode);
    }
  }
}
