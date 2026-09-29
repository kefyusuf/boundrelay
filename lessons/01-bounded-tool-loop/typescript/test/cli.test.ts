import {mkdtemp} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

import {describe, expect, it} from "vitest";

import {parseCliOptions, runCli} from "../src/cli.js";

describe("M1 CLI", () => {
  it("parses exactly the three required options", () => {
    expect(parseCliOptions([
      "--mode", "direct",
      "--case", "direct-order-status",
      "--trace", "/tmp/t.jsonl",
    ])).toEqual({
      mode: "direct",
      caseId: "direct-order-status",
      tracePath: "/tmp/t.jsonl",
    });
  });

  it("rejects duplicate and unknown options", () => {
    expect(() => parseCliOptions([
      "--mode", "direct",
      "--mode", "agent",
      "--case", "x",
      "--trace", "y",
    ])).toThrow("Duplicate option --mode");
    expect(() => parseCliOptions([
      "--mode", "direct",
      "--case", "x",
      "--trace", "y",
      "--other", "z",
    ])).toThrow("Unexpected argument --other");
  });

  it("prints exactly one JSON result line", async () => {
    const directory = await mkdtemp(join(tmpdir(), "br-m1-cli-"));
    let stdout = "";
    let stderr = "";
    const code = await runCli([
      "--mode", "direct",
      "--case", "direct-order-status",
      "--trace", join(directory, "trace.jsonl"),
    ], (value) => { stdout += value; }, (value) => { stderr += value; });

    expect(code).toBe(0);
    expect(stderr).toBe("");
    expect(stdout.trim().split("\n")).toHaveLength(1);
    expect(JSON.parse(stdout)).toMatchObject({status: "SUCCEEDED", case_id: "direct-order-status"});
  });

  it("treats case/mode mismatch as CLI configuration error", async () => {
    let stdout = "";
    let stderr = "";
    const code = await runCli([
      "--mode", "direct",
      "--case", "agent-delayed-shipment",
      "--trace", "/tmp/x.jsonl",
    ], (value) => { stdout += value; }, (value) => { stderr += value; });

    expect(code).toBe(2);
    expect(stdout).toBe("");
    expect(stderr).toContain("mode");
  });
});
