import {validateRouteDecision} from "./schemas.js";
import type {FailureCode, RouteDecision} from "./types.js";

export type RouteDecisionResult =
  | {ok: true; decision: RouteDecision}
  | {ok: false; failureCode: FailureCode; rejectedRoute: string | null};

export function routeDecision(raw: unknown): RouteDecisionResult {
  const validated = validateRouteDecision(raw);
  if (validated.ok) {
    return {ok: true, decision: validated.value};
  }

  const rejectedRoute = typeof raw === "object"
    && raw !== null
    && "route" in raw
    && typeof (raw as Record<string, unknown>).route === "string"
    ? (raw as Record<string, unknown>).route as string
    : null;

  return {ok: false, failureCode: "INVALID_ROUTE_DECISION", rejectedRoute};
}
