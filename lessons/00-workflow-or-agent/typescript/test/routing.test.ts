import {describe, expect, it} from "vitest";

import {routeDecision} from "../src/bounded-router.js";
import {classifyDeterministically} from "../src/deterministic-router.js";

describe("routing", () => {
  it("classifies the three deterministic support routes", () => {
    expect(classifyDeterministically("I was charged twice")).toEqual({route: "billing", confidence: 1});
    expect(classifyDeterministically("The app shows an error")).toEqual({route: "technical", confidence: 1});
    expect(classifyDeterministically("What are your hours?")).toEqual({route: "general", confidence: 1});
  });

  it("rejects an unknown model route before dispatch", () => {
    expect(routeDecision({route: "unknown-specialist", confidence: 0.99})).toEqual({
      ok: false,
      failureCode: "INVALID_ROUTE_DECISION",
      rejectedRoute: "unknown-specialist",
    });
  });
});
