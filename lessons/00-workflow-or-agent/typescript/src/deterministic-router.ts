import type {RouteDecision} from "./types.js";

const BILLING_KEYWORDS = ["charged", "charge", "invoice", "payment", "refund", "billed"] as const;
const TECHNICAL_KEYWORDS = ["error", "crash", "cannot log in", "can't log in", "bug", "broken"] as const;

export function classifyDeterministically(request: string): RouteDecision {
  const value = request.toLowerCase();
  if (BILLING_KEYWORDS.some((keyword) => value.includes(keyword))) {
    return {route: "billing", confidence: 1};
  }
  if (TECHNICAL_KEYWORDS.some((keyword) => value.includes(keyword))) {
    return {route: "technical", confidence: 1};
  }
  return {route: "general", confidence: 1};
}
