export type Route = "billing" | "technical" | "general";
export type RouterMode = "code" | "model";
export type ReceiverName = "billing-specialist" | "technical-specialist" | "general-specialist";
export type PolicyOutcome = "selected" | "fallback";
export type FailureCode = "INVALID_ROUTE_DECISION" | "HANDOFF_CONTEXT_INVALID" | "HANDOFF_RECEIVER_UNAVAILABLE";
export interface RouteDecision {route: Route; confidence: number}
export interface RouteDecisionInput {caseId: string; request: string}
export interface RouteDecisionProvider {nextDecision(input: RouteDecisionInput): Promise<unknown>}
export interface RouteSelection {proposedRoute: Route; selectedRoute: Route; confidence: number; policyOutcome: PolicyOutcome; fallbackApplied: boolean; receiver: ReceiverName}
export interface ReceiverInput {ticket_id: string; request_text: string}
export interface SenderIntent {route: Route; confidence: number; policy_outcome: PolicyOutcome}
export interface HandoffEnvelope {schema_version: "1.0"; handoff_id: string; sender: "support-router"; receiver: ReceiverName; sender_intent: SenderIntent; receiver_input: ReceiverInput}
export interface HandoffResult {schema_version: "1.0"; run_id: string; scenario_id: "support-handoff"; case_id: string; router_mode: RouterMode; status: "SUCCEEDED" | "FAILED"; proposed_route: Route | null; selected_route: Route | null; receiver: ReceiverName | null; fallback_applied: boolean; specialist_invoked: boolean; failure_code: FailureCode | null; trace_path: string}
export interface ReceiverDefinition {name: ReceiverName; handle(input: ReceiverInput): Promise<void>}
export interface ReceiverDirectory {resolve(name: string): ReceiverDefinition | undefined}
export interface ScenarioCase {id: string; ticket_id: string; request: string; router_mode: RouterMode; expected_status: "SUCCEEDED" | "FAILED"; expected_proposed_route: Route; expected_confidence: number; expected_selected_route: Route; expected_receiver: ReceiverName; expected_policy_outcome: PolicyOutcome; expected_fallback_applied: boolean; expected_specialist_invoked: boolean; expected_failure_code: FailureCode | null; failure_ref?: string}
export interface ScenarioDefinition {schema_version: "1.0"; scenario_id: "support-handoff"; confidence_threshold: number; route_receivers: Record<Route, ReceiverName>; cases: ScenarioCase[]}
export interface FailureFixture {omit_receiver_input_fields?: readonly "request_text"[]; unavailable_receivers?: readonly ReceiverName[]}
export type FailureFixtures = Record<string, FailureFixture>;
export type ValidationResult<T> = {ok: true; value: T} | {ok: false; errors: string[]};
export type EventSource = "typescript" | "python";
export type EventType = "run.created" | "run.started" | "run.completed" | "run.failed" | "model.requested" | "model.completed" | "route.selected" | "route.rejected" | "handoff.requested" | "handoff.accepted" | "handoff.rejected";
export interface RunEvent {schema_version: "1.0"; event_id: string; run_id: string; sequence: number; type: EventType; timestamp: string; source: EventSource; data: Record<string, unknown>}
