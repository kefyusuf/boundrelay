export const ROUTES = ["billing", "technical", "general"] as const;
export type Route = (typeof ROUTES)[number];
export type RouterMode = "code" | "model";
export const RECEIVER_NAMES = [
  "billing-specialist",
  "technical-specialist",
  "general-specialist",
] as const;
export type ReceiverName = (typeof RECEIVER_NAMES)[number];
export type PolicyOutcome = "selected" | "fallback";
export const FAILURE_CODES = [
  "INVALID_ROUTE_DECISION",
  "HANDOFF_CONTEXT_INVALID",
  "HANDOFF_RECEIVER_UNAVAILABLE",
] as const;
export type FailureCode = (typeof FAILURE_CODES)[number];
export type RunStatus = "SUCCEEDED" | "FAILED";

export const EVENT_TYPES = [
  "run.created", "run.started", "run.completed", "run.failed",
  "step.started", "step.completed", "step.failed",
  "model.requested", "model.completed", "model.failed",
  "route.selected", "route.rejected",
  "tool.requested", "tool.completed", "tool.failed",
  "budget.consumed", "budget.exceeded",
  "handoff.requested", "handoff.accepted", "handoff.rejected",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];
export type EventSource = "typescript" | "python";

export interface RouteDecision { route: Route; confidence: number; }
export interface RouteDecisionInput { caseId: string; request: string; }
export interface RouteDecisionProvider { nextDecision(input: RouteDecisionInput): Promise<unknown>; }

export interface RouteSelection {
  proposedRoute: Route;
  selectedRoute: Route;
  confidence: number;
  policyOutcome: PolicyOutcome;
  fallbackApplied: boolean;
  receiver: ReceiverName;
}

export interface ReceiverInput { ticket_id: string; request_text: string; }
export interface SenderIntent { route: Route; confidence: number; policy_outcome: PolicyOutcome; }
export interface HandoffEnvelope {
  schema_version: "1.0";
  handoff_id: string;
  sender: "support-router";
  receiver: ReceiverName;
  sender_intent: SenderIntent;
  receiver_input: ReceiverInput;
}

export interface HandoffResult {
  schema_version: "1.0";
  run_id: string;
  scenario_id: "support-handoff";
  case_id: string;
  router_mode: RouterMode;
  status: RunStatus;
  proposed_route: Route | null;
  selected_route: Route | null;
  receiver: ReceiverName | null;
  fallback_applied: boolean;
  specialist_invoked: boolean;
  failure_code: FailureCode | null;
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

export interface ScenarioCase {
  id: string;
  ticket_id: string;
  request: string;
  router_mode: RouterMode;
  expected_status: RunStatus;
  expected_proposed_route: Route;
  expected_confidence: number;
  expected_selected_route: Route;
  expected_receiver: ReceiverName;
  expected_policy_outcome: PolicyOutcome;
  expected_fallback_applied: boolean;
  expected_specialist_invoked: boolean;
  expected_failure_code?: FailureCode;
  failure_ref?: string;
}

export interface ScenarioDefinition {
  schema_version: "1.0";
  scenario_id: "support-handoff";
  confidence_threshold: number;
  route_receivers: Record<Route, ReceiverName>;
  cases: ScenarioCase[];
}

export type ReceiverInputField = keyof ReceiverInput;
export type FailureFixture =
  | {omit_receiver_input_fields: ReceiverInputField[]}
  | {unavailable_receivers: ReceiverName[]};
export type FailureFixtures = Record<string, FailureFixture>;

export type ValidationResult<T> =
  | {ok: true; value: T}
  | {ok: false; errors: string[]};

export interface ReceiverDefinition {
  name: ReceiverName;
  handle(input: ReceiverInput): Promise<void>;
}
export interface ReceiverDirectory { resolve(name: string): ReceiverDefinition | undefined; }
