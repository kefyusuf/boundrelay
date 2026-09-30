import {mkdtempSync, readFileSync, rmSync} from "node:fs";
import net from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {afterAll, beforeAll, describe, expect, it} from "vitest";
import type {ReceiverDefinition, ReceiverDirectory, ReceiverInput, RouteDecisionProvider} from "../src/types.js";

type RunScenarioCase = typeof import("../src/runner.js").runScenarioCase;
let runScenarioCase: RunScenarioCase;
const originalConnect = net.Socket.prototype.connect;
const originalFetch = globalThis.fetch;

beforeAll(async () => {
  net.Socket.prototype.connect = function blockedConnect() { throw new Error("network access is forbidden"); } as any;
  globalThis.fetch = async () => { throw new Error("network access is forbidden"); };
  await expect(import("./offline-import-probe.js")).rejects.toThrow("network access is forbidden");
  ({runScenarioCase} = await import("../src/runner.js"));
});

afterAll(() => { net.Socket.prototype.connect = originalConnect; globalThis.fetch = originalFetch; });

function ids(prefix="id"){let n=0;return()=>`${prefix}-${++n}`}
function events(path:string): any[]{return readFileSync(path,"utf8").trim().split("\n").map((x:string)=>JSON.parse(x));}
async function run(caseId:string,mode:"code"|"model", extra:Record<string,unknown>={}){
 const dir=mkdtempSync(join(tmpdir(),"boundrelay-m2-run-")); const path=join(dir,"trace.jsonl");
 try { const result=await runScenarioCase({mode,caseId,tracePath:path,clock:()=>new Date("2026-09-30T00:00:00Z"),idFactory:ids(caseId),...extra}); return {result,events:events(path)}; }
 finally { rmSync(dir,{recursive:true,force:true}); }
}

describe("M2 typed handoff runtime", () => {
 it("runs code billing with no model events", async()=>{
   const {result,events:e}=await run("code-billing-handoff","code");
   expect(result).toMatchObject({status:"SUCCEEDED",proposed_route:"billing",selected_route:"billing",receiver:"billing-specialist",fallback_applied:false,specialist_invoked:true,failure_code:null});
   expect(e.filter((x:any)=>String(x.type).startsWith("model.")).length).toBe(0);
   expect(e.map((x:any)=>x.type).filter((x:any)=>["route.selected","handoff.requested","handoff.accepted","run.completed"].includes(x))).toEqual(["route.selected","handoff.requested","handoff.accepted","run.completed"]);
 });
 it("runs model technical with exactly one model decision", async()=>{
   const {result,events:e}=await run("model-technical-handoff","model");
   expect(result).toMatchObject({status:"SUCCEEDED",proposed_route:"technical",selected_route:"technical",receiver:"technical-specialist",fallback_applied:false,specialist_invoked:true});
   expect(e.filter((x:any)=>x.type==="model.requested").length).toBe(1);
   expect(e.filter((x:any)=>x.type==="model.completed").length).toBe(1);
 });
 it("keeps proposed billing intent while low confidence selects general receiver", async()=>{
   const {result,events:e}=await run("model-low-confidence-fallback","model");
   expect(result).toMatchObject({proposed_route:"billing",selected_route:"general",receiver:"general-specialist",fallback_applied:true,specialist_invoked:true});
   const requested=e.find((x:any)=>x.type==="handoff.requested");
   expect(requested.data.sender_intent.route).toBe("billing");
   expect(requested.data.receiver).toBe("general-specialist");
 });
 it("rejects context loss before receiver resolution or invocation", async()=>{
   let resolves=0; let handles=0;
   const directory:ReceiverDirectory={resolve(){resolves++;return {name:"billing-specialist",async handle(){handles++;}}}};
   const {result,events:e}=await run("handoff-context-loss","model",{receiverDirectory:directory});
   expect(result).toMatchObject({status:"FAILED",failure_code:"HANDOFF_CONTEXT_INVALID",specialist_invoked:false,receiver:"billing-specialist"});
   expect(e.map((x:any)=>x.type).filter((x:any)=>String(x).startsWith("handoff."))).toEqual(["handoff.requested","handoff.rejected"]);
   expect(resolves).toBe(0); expect(handles).toBe(0);
 });
 it("rejects unavailable receiver without fallback or invocation", async()=>{
   let resolves=0; let handles=0;
   const directory:ReceiverDirectory={resolve(){resolves++;return {name:"billing-specialist",async handle(){handles++;}}}};
   const {result,events:e}=await run("handoff-receiver-unavailable","code",{receiverDirectory:directory});
   expect(result).toMatchObject({status:"FAILED",failure_code:"HANDOFF_RECEIVER_UNAVAILABLE",selected_route:"billing",receiver:"billing-specialist",specialist_invoked:false});
   expect(e.map((x:any)=>x.type).filter((x:any)=>String(x).startsWith("handoff."))).toEqual(["handoff.requested","handoff.rejected"]);
   expect(resolves).toBe(0); expect(handles).toBe(0);
 });
 it("fails invalid model route before handoff and receiver resolution", async()=>{
   let resolves=0;
   const provider:RouteDecisionProvider={async nextDecision(){return {route:"unknown",confidence:0.9}}};
   const directory:ReceiverDirectory={resolve(){resolves++;return undefined}};
   const {result,events:e}=await run("model-technical-handoff","model",{routeProvider:provider,receiverDirectory:directory});
   expect(result).toMatchObject({status:"FAILED",failure_code:"INVALID_ROUTE_DECISION",proposed_route:null,selected_route:null,receiver:null,fallback_applied:false,specialist_invoked:false});
   expect(e.some((x:any)=>String(x.type).startsWith("handoff."))).toBe(false);
   expect(e.some((x:any)=>x.type==="route.rejected")).toBe(true);
   expect(resolves).toBe(0);
 });
 it("invokes exactly one receiver with only ticket_id and request_text", async()=>{
   const seen:ReceiverInput[]=[];
   const definition:ReceiverDefinition={name:"billing-specialist",async handle(input){seen.push(structuredClone(input))}};
   const directory:ReceiverDirectory={resolve(name){return name==="billing-specialist"?definition:undefined}};
   const {result}=await run("code-billing-handoff","code",{receiverDirectory:directory});
   expect(result.specialist_invoked).toBe(true);
   expect(seen).toHaveLength(1);
   expect(Object.keys(seen[0]!).sort()).toEqual(["request_text","ticket_id"]);
 });
 it("treats receiver exception as tooling failure after accepted handoff", async()=>{
   let calls=0;
   const definition:ReceiverDefinition={name:"billing-specialist",async handle(){calls++;throw new Error("receiver exploded")}};
   const directory:ReceiverDirectory={resolve(){return definition}};
   const dir=mkdtempSync(join(tmpdir(),"boundrelay-m2-explode-")); const path=join(dir,"trace.jsonl");
   try {
     await expect(runScenarioCase({mode:"code",caseId:"code-billing-handoff",tracePath:path,receiverDirectory:directory,idFactory:ids("x")})).rejects.toThrow("receiver exploded");
     expect(calls).toBe(1);
     const e=events(path);
     expect(e.some((x:any)=>x.type==="handoff.accepted")).toBe(true);
     expect(e.some((x:any)=>x.type==="handoff.rejected")).toBe(false);
   } finally {rmSync(dir,{recursive:true,force:true});}
 });

 it("emits the exact successful event payload boundary", async()=>{
   const {events:e}=await run("model-low-confidence-fallback","model");
   expect(e[0].data).toEqual({scenario_id:"support-handoff",case_id:"model-low-confidence-fallback",router_mode:"model"});
   expect(e[1].data).toEqual({case_id:"model-low-confidence-fallback",router_mode:"model"});
   expect(e.find((x:any)=>x.type==="model.requested").data).toEqual({case_id:"model-low-confidence-fallback"});
   expect(e.find((x:any)=>x.type==="model.completed").data).toEqual({case_id:"model-low-confidence-fallback",decision:{route:"billing",confidence:0.54}});
   expect(e.find((x:any)=>x.type==="route.selected").data).toEqual({router_mode:"model",proposed_route:"billing",selected_route:"general",confidence:0.54,fallback_applied:true});
   const requested=e.find((x:any)=>x.type==="handoff.requested");
   expect(Object.keys(requested.data).sort()).toEqual(["handoff_id","receiver","receiver_input","sender","sender_intent"]);
   expect(requested.data.sender_intent).toEqual({route:"billing",confidence:0.54,policy_outcome:"fallback"});
   expect(requested.data.receiver_input).toEqual({ticket_id:"TCK-1003",request_text:"Something about my invoice looks wrong but I am not sure what happened."});
   const terminal=e.at(-1);
   expect(terminal.data).toEqual({status:"SUCCEEDED",proposed_route:"billing",selected_route:"general",receiver:"general-specialist",fallback_applied:true,specialist_invoked:true});
 });
 it("keeps provider exceptions as tooling failures before handoff", async()=>{
   const provider:RouteDecisionProvider={async nextDecision(){throw new Error("provider fixture broken")}};
   const dir=mkdtempSync(join(tmpdir(),"boundrelay-m2-provider-")); const path=join(dir,"trace.jsonl");
   try {
     await expect(runScenarioCase({mode:"model",caseId:"model-technical-handoff",tracePath:path,routeProvider:provider,idFactory:ids("p")})).rejects.toThrow("provider fixture broken");
     const e=events(path); expect(e.filter((x:any)=>x.type==="model.requested")).toHaveLength(1); expect(e.some((x:any)=>String(x.type).startsWith("handoff."))).toBe(false); expect(e.some((x:any)=>x.type==="run.failed"||x.type==="run.completed")).toBe(false);
   } finally {rmSync(dir,{recursive:true,force:true});}
 });
 it("keeps stable run id, contiguous sequences, and one terminal event for canonical outcomes", async()=>{
   const all: Array<[string,"code"|"model"]> = [["code-billing-handoff","code"],["model-technical-handoff","model"],["model-low-confidence-fallback","model"],["handoff-context-loss","model"],["handoff-receiver-unavailable","code"]];
   for(const [caseId,mode] of all){const {result,events:e}=await run(caseId,mode);expect(e.every((x:any)=>x.run_id===result.run_id)).toBe(true);expect(e.map((x:any)=>x.sequence)).toEqual(e.map((_x:any,i:number)=>i+1));expect(e.filter((x:any)=>x.type==="run.completed"||x.type==="run.failed")).toHaveLength(1);expect(String(e.at(-1).type).startsWith("run.")).toBe(true);expect(e.some((x:any)=>String(x.type).startsWith("step."))).toBe(false);}
 });
});
