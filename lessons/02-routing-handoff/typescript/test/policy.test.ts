import {describe, expect, it} from "vitest";
import {applyConfidencePolicy, classifyWithCode} from "../src/policy.js";

describe("M2 deterministic routing and confidence policy", () => {
  it("keeps equality at 0.80 on the proposed route", () => {
    expect(applyConfidencePolicy({route: "billing", confidence: 0.80})).toMatchObject({
      proposedRoute: "billing", selectedRoute: "billing", receiver: "billing-specialist",
      policyOutcome: "selected", fallbackApplied: false,
    });
  });
  it("falls 0.79 back to general", () => {
    expect(applyConfidencePolicy({route: "billing", confidence: 0.79})).toMatchObject({
      proposedRoute: "billing", selectedRoute: "general", receiver: "general-specialist",
      policyOutcome: "fallback", fallbackApplied: true,
    });
  });
  it("maps all routes and ignores model-provided receiver fields", () => {
    expect(applyConfidencePolicy({route: "technical", confidence: 0.95}).receiver).toBe("technical-specialist");
    expect(applyConfidencePolicy({route: "general", confidence: 0.95}).receiver).toBe("general-specialist");
    expect(applyConfidencePolicy({route: "billing", confidence: 0.95, receiver: "technical-specialist"} as never).receiver).toBe("billing-specialist");
  });
  it("copies the accepted deterministic keyword baseline", () => {
    expect(classifyWithCode("I was charged twice")).toEqual({route: "billing", confidence: 1});
    expect(classifyWithCode("The app shows an error")).toEqual({route: "technical", confidence: 1});
    expect(classifyWithCode("What are your opening hours?")).toEqual({route: "general", confidence: 1});
  });
});
