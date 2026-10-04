import {mkdtempSync, readFileSync, rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {describe, expect, it} from "vitest";
import {MemoryEventSink, writeJsonl} from "../src/trace.js";

describe("M2 trace sink", () => {
  it("sanitizes non-JSON values and writes strict LF JSONL", async () => {
    let n=0;
    const sink=new MemoryEventSink({runId:"run-1",source:"typescript",clock:()=>new Date("2026-09-30T00:00:00Z"),idFactory:()=>`id-${++n}`});
    sink.emit("model.completed", {case_id:"x",decision:{value:BigInt(1),bad:Number.NaN}});
    const dir=mkdtempSync(join(tmpdir(),"boundrelay-m2-trace-")); const path=join(dir,"trace.jsonl");
    try {
      await writeJsonl(path,sink.events);
      const raw=readFileSync(path);
      expect(raw.at(-1)).toBe(10);
      expect(raw.includes(13)).toBe(false);
      const event=JSON.parse(raw.toString("utf8").trim());
      expect(event.sequence).toBe(1);
      expect(event.data.decision.value).toBeNull();
      expect(event.data.decision.bad).toBeNull();
    } finally { rmSync(dir,{recursive:true,force:true}); }
  });
});
