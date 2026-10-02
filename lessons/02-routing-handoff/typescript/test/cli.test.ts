import {it, expect} from "vitest";
import {parseCliOptions, runCli} from "../src/cli.js";
import {mkdtemp, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
it("consumes exactly the required CLI options", () => {
  const args = ["--mode", "code", "--case", "code-billing-handoff", "--trace", "t.jsonl"];
  expect(parseCliOptions(args)).toEqual({mode: "code", caseId: "code-billing-handoff", tracePath: "t.jsonl"});
  for (const bad of [[...args, "--mode", "model"], [...args, "--other", "x"], [...args, "positional"], ["--mode"], ["--mode", "auto", ...args.slice(2)]]) expect(() => parseCliOptions(bad)).toThrow();
});
it("prints one JSON domain outcome and reports tooling errors with exit 2", async () => {
  const dir = await mkdtemp(join(tmpdir(), "br-m2-cli-"));
  try {
    for (const [mode, caseId, status] of [["code", "code-billing-handoff", "SUCCEEDED"], ["model", "handoff-context-loss", "FAILED"]]) {
      let out = "", err = "";
      expect(await runCli(["--mode", mode!, "--case", caseId!, "--trace", join(dir, "t.jsonl")], s => {out += s;}, s => {err += s;})).toBe(0);
      expect(out.trim().split("\n")).toHaveLength(1); expect(JSON.parse(out).status).toBe(status); expect(err).toBe("");
    }
    let out = "", err = "";
    expect(await runCli(["--mode", "code", "--case", "model-technical-handoff", "--trace", "x"], s => {out += s;}, s => {err += s;})).toBe(2);
    expect(out).toBe(""); expect(err).toContain("mode");
  } finally {await rm(dir, {recursive: true, force: true});}
});
