import {describe, expect, it} from "vitest";

import {parseCliOptions} from "../src/cli.js";

const VALID: string[] = [
  "--mode",
  "model",
  "--case",
  "billing-duplicate-charge",
  "--trace",
  "/tmp/trace.jsonl",
];

const INVALID_ARGUMENTS: Array<{name: string; args: string[]}> = [
  {name: "unknown option", args: [...VALID, "--unknown", "value"]},
  {name: "positional argument", args: [...VALID, "positional-value"]},
  {name: "duplicate option", args: [...VALID, "--mode", "deterministic"]},
];

describe("CLI option parsing", () => {
  it("accepts each required option exactly once", () => {
    expect(parseCliOptions(VALID)).toEqual({
      mode: "model",
      caseId: "billing-duplicate-charge",
      tracePath: "/tmp/trace.jsonl",
    });
  });

  it.each(INVALID_ARGUMENTS)("rejects $name", ({args}) => {
    expect(() => parseCliOptions(args)).toThrow(/unexpected|duplicate/i);
  });
});
