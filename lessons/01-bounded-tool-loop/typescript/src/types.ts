export const TOOL_NAMES = ["lookup_order", "lookup_shipment"] as const;
export type ToolName = (typeof TOOL_NAMES)[number];
export type ToolSideEffect = "READ_ONLY";
export type RunMode = "direct" | "agent";
export type RunStatus = "SUCCEEDED" | "FAILED";
export const FAILURE_CODES = [
  "UNKNOWN_TOOL",
  "INVALID_TOOL_ARGUMENTS",
  "TOOL_TIMEOUT",
  "TOOL_EXECUTION_FAILED",
  "STEP_BUDGET_EXCEEDED",
  "TOKEN_BUDGET_EXCEEDED",
  "INVALID_MODEL_DECISION",
] as const;
export type FailureCode = (typeof FAILURE_CODES)[number];

export const EVENT_TYPES = [
  "run.created",
  "run.started",
  "run.completed",
  "run.failed",
  "step.started",
  "step.completed",
  "step.failed",
  "model.requested",
  "model.completed",
  "model.failed",
  "route.selected",
  "route.rejected",
  "tool.requested",
  "tool.completed",
  "tool.failed",
  "budget.consumed",
  "budget.exceeded",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];
export type EventSource = "typescript" | "python";

export interface ToolCallDecision {
  kind: "tool_call";
  call_id: string;
  tool: string;
  arguments: Record<string, unknown>;
}

export interface FinalDecision {
  kind: "final";
  answer: string;
}

export interface ModelTurn {
  schema_version: "1.0";
  decision: ToolCallDecision | FinalDecision;
  usage: {
    input_tokens: number;
    output_tokens: number;
  };
}

export interface ToolObservation {
  call_id: string;
  tool: ToolName;
  output: Record<string, unknown>;
}

export interface RunResult {
  schema_version: "1.0";
  run_id: string;
  scenario_id: "order-investigation";
  case_id: string;
  mode: RunMode;
  status: RunStatus;
  answer: string | null;
  failure_code: FailureCode | null;
  model_steps: number;
  tokens_used: number;
  tool_invocations: number;
  trace_path: string;
}

export interface RunEvent {
  schema_version: "1.0";
  event_id: string;
  run_id: string;
  sequence: number;
  type: EventType;
  timestamp: string;
  source: EventSource;
  data: Record<string, unknown>;
}

export interface DirectCall {
  call_id: string;
  tool: ToolName;
  arguments: Record<string, unknown>;
}

interface ScenarioCaseBase {
  id: string;
  mode: RunMode;
  request: string;
  max_steps: number;
  max_tokens: number;
  expected_model_steps: number;
  expected_tokens_used: number;
  expected_tool_invocations: number;
}

export interface ScenarioSuccessCase extends ScenarioCaseBase {
  expected_status: "SUCCEEDED";
  expected_answer: string;
  direct_call?: DirectCall;
}

export interface ScenarioFailureCase extends ScenarioCaseBase {
  mode: "agent";
  expected_status: "FAILED";
  expected_failure_code: FailureCode;
}

export type ScenarioCase = ScenarioSuccessCase | ScenarioFailureCase;

export interface ScenarioDefinition {
  schema_version: "1.0";
  scenario_id: "order-investigation";
  cases: ScenarioCase[];
}

export interface ModelInput {
  caseId: string;
  request: string;
  modelStep: number;
  observations: readonly ToolObservation[];
}

export interface ModelProvider {
  nextTurn(input: ModelInput): Promise<unknown>;
}

export type ValidationResult<T> =
  | {ok: true; value: T}
  | {ok: false; errors: string[]};

export interface ToolDefinition {
  name: ToolName;
  sideEffect: "READ_ONLY";
  timeoutMs: number;
  validateArguments(value: unknown): ValidationResult<Record<string, unknown>>;
  invoke(argumentsValue: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export interface ToolRegistry {
  resolve(name: string): ToolDefinition | undefined;
}
