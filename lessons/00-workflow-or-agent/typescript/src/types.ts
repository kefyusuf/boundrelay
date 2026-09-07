export const ROUTES = ["billing", "technical", "general"] as const;
export type Route = (typeof ROUTES)[number];

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
] as const;

export type EventType = (typeof EVENT_TYPES)[number];
export type EventSource = "typescript" | "python";
export type RunMode = "deterministic" | "model";
export type RunStatus = "SUCCEEDED" | "FAILED";
export type FailureCode = "INVALID_ROUTE_DECISION";

export interface RouteDecision {
  route: Route;
  confidence: number;
}

export interface DecisionProvider {
  classify(input: {caseId: string; request: string}): Promise<unknown>;
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

export interface RunResult {
  schema_version: "1.0";
  run_id: string;
  scenario_id: "support-triage";
  case_id: string;
  mode: RunMode;
  status: RunStatus;
  selected_route: Route | null;
  specialist_invoked: boolean;
  failure_code: FailureCode | null;
  trace_path: string;
}

export interface ScenarioSuccessCase {
  id: string;
  request: string;
  expected_route: Route;
}

export interface ScenarioFailureCase {
  id: string;
  request: string;
  expected_failure_code: FailureCode;
}

export type ScenarioCase = ScenarioSuccessCase | ScenarioFailureCase;

export interface ScenarioDefinition {
  schema_version: "1.0";
  scenario_id: "support-triage";
  routes: Route[];
  cases: ScenarioCase[];
}

export interface SpecialistInvocation {
  route: Route;
  request: string;
}

export interface SpecialistDispatcher {
  dispatch(invocation: SpecialistInvocation): Promise<void>;
}

export type ValidationResult<T> =
  | {ok: true; value: T}
  | {ok: false; errors: string[]};
