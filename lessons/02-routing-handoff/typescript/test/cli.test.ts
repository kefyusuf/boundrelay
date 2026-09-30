import {mkdtempSync, rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {describe, expect, it} from "vitest";
import {parseCliOptions, runCli} from "../src/cli.js";

describe("M2 CLI", () => {
  it("parses exactly mode/case/trace", () => {
    expect(parseCliOptions(["--mode","code","--case","code-billing-handoff","--trace","/tmp/x.jsonl"])).toEqual({mode:"code",caseId:"code-billing-handoff",tracePath:"/tmp/x.jsonl"});
  });
  it("rejects unknown, duplicate, positional, and missing options", () => {
    expect(()=>parseCliOptions(["--mode","code","--case","x","--trace","y","--other","z"])).toThrow("Unexpected argument");
    expect(()=>parseCliOptions(["--mode","code","--mode","model","--case","x","--trace","y"])).toThrow("Duplicate option");
    expect(()=>parseCliOptions(["positional","x","--mode","code","--case","x","--trace","y"])).toThrow("Unexpected argument");
    expect(()=>parseCliOptions(["--mode","code","--case","x"])).toThrow("Missing required option --trace");
  });
  it("prints one JSON line and exit 0 for domain failure", async () => {
    const dir=mkdtempSync(join(tmpdir(),"boundrelay-m2-cli-")); const trace=join(dir,"trace.jsonl"); let out="",err="";
    try { const code=await runCli(["--mode","code","--case","handoff-receiver-unavailable","--trace",trace],(v:string)=>{out+=v},(v:string)=>{err+=v}); expect(code).toBe(0); expect(out.trim().split("\n")).toHaveLength(1); expect(JSON.parse(out).failure_code).toBe("HANDOFF_RECEIVER_UNAVAILABLE"); expect(err).toBe(""); }
    finally {rmSync(dir,{recursive:true,force:true});}
  });
  it("reports tooling failure on stderr and exit 2", async () => {
    const dir=mkdtempSync(join(tmpdir(),"boundrelay-m2-cli-tool-")); const trace=join(dir,"trace.jsonl"); let out="",err="";
    const failingRunner=async()=>{throw new Error("boom")};
    try { const code=await runCli(["--mode","code","--case","code-billing-handoff","--trace",trace],(v:string)=>{out+=v},(v:string)=>{err+=v},failingRunner); expect(code).toBe(2); expect(out).toBe(""); expect(err).toContain("boom"); }
    finally {rmSync(dir,{recursive:true,force:true});}
  });
});
