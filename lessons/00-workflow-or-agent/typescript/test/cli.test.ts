import {describe, expect, it} from "vitest";

import {parseCliOptions} from "../src/cli.js";

const VALID = [
  "--mode",
  "model",
  "--case",
  "billing-duplicate-charge",
  "--trace",
  "/tmp/trace.jsonl",
];

describe("CLI option parsing", () => {
  it("accepts each required option exactly once", () => {
    expect(parseCliOptions(VALID)).toEqual({
      mode: "model",
      caseId: "billing-duplicate-charge",
      tracePath: "/tmp/trace.jsonl",
    });
  });

  it.each([
    [...VALID, "--unknown", "value"],
    [...VALID, "positional-value"],
    [...VALID, "--mode", "deterministic"],
  ])("rejects unconsumed or duplicate arguments: %j", (args) => {
    expect(() => parseCliOptions(args)).toThrow(/unexpected|duplicate/i);
  });
});
