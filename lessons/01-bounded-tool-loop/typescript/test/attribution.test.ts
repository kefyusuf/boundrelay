import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runScenarioCase} from '../src/runner.js';
import {validateRunResult} from '../src/schemas.js';
import type {RunResult} from '../src/types.js';

let sequence=0;const ids=()=>`probe-${++sequence}`;
const clock=()=>new Date('2026-09-02T00:00:00.000Z');

test('attribution_present_and_sums_match',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m1-attr-'));
 try{
  const direct=await runScenarioCase({mode:'direct',caseId:'direct-order-status',tracePath:join(tmp,'d.jsonl'),clock,idFactory:ids});
  const agent=await runScenarioCase({mode:'agent',caseId:'agent-delayed-shipment',tracePath:join(tmp,'a.jsonl'),clock,idFactory:ids});
  expect(direct.attribution).toEqual({steps:[
   {step_name:'tool.lookup_order',latency_ms:8,cost_cents:1,attempts:1}],
   totals:{latency_ms:8,cost_cents:1,attempts:1}});
  expect(agent.attribution).toEqual({steps:[
   {step_name:'model',latency_ms:90,cost_cents:6,attempts:3},
   {step_name:'tool.lookup_order',latency_ms:8,cost_cents:1,attempts:1},
   {step_name:'tool.lookup_shipment',latency_ms:9,cost_cents:1,attempts:1}],
   totals:{latency_ms:107,cost_cents:8,attempts:5}});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('attribution_absent_rejected_by_schema',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m1-attr-'));
 try{
  const result:RunResult=await runScenarioCase({mode:'direct',caseId:'direct-order-status',tracePath:join(tmp,'t.jsonl'),clock,idFactory:ids});
  const stripped={...result} as Partial<RunResult>;delete stripped.attribution;
  expect(validateRunResult(result).ok).toBe(true);
  expect(validateRunResult(stripped as RunResult).ok).toBe(false);
 } finally{rmSync(tmp,{recursive:true,force:true});}
});
