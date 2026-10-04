import type {ReceiverName, Route, RouteDecision, RouteSelection} from "./types.js";
const BILLING_KEYWORDS = ["charged", "charge", "invoice", "payment", "refund", "billed"] as const;
const TECHNICAL_KEYWORDS = ["error", "crash", "cannot log in", "can't log in", "bug", "broken"] as const;
const RECEIVERS: Record<Route, ReceiverName> = {billing:"billing-specialist", technical:"technical-specialist", general:"general-specialist"};
export const CONFIDENCE_THRESHOLD = 0.80;
export function classifyWithCode(request: string): RouteDecision {
  const value = request.toLowerCase();
  if (BILLING_KEYWORDS.some((keyword) => value.includes(keyword))) return {route:"billing", confidence:1};
  if (TECHNICAL_KEYWORDS.some((keyword) => value.includes(keyword))) return {route:"technical", confidence:1};
  return {route:"general", confidence:1};
}
export function applyConfidencePolicy(decision: RouteDecision): RouteSelection {
  const fallbackApplied = decision.confidence < CONFIDENCE_THRESHOLD;
  const selectedRoute: Route = fallbackApplied ? "general" : decision.route;
  return {
    proposedRoute: decision.route,
    selectedRoute,
    confidence: decision.confidence,
    policyOutcome: fallbackApplied ? "fallback" : "selected",
    fallbackApplied,
    receiver: RECEIVERS[selectedRoute],
  };
}
