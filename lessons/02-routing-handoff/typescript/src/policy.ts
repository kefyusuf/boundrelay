import type {Route, ReceiverName, RouteDecision, RouteSelection} from "./types.js";
export const ROUTE_RECEIVERS: Readonly<Record<Route, ReceiverName>> = Object.freeze({billing: "billing-specialist", technical: "technical-specialist", general: "general-specialist"});
export function applyConfidencePolicy(decision: RouteDecision): RouteSelection {
  const fallbackApplied = decision.confidence < 0.80;
  const selectedRoute = fallbackApplied ? "general" : decision.route;
  return {proposedRoute: decision.route, selectedRoute, confidence: decision.confidence, policyOutcome: fallbackApplied ? "fallback" : "selected", fallbackApplied, receiver: ROUTE_RECEIVERS[selectedRoute]};
}
