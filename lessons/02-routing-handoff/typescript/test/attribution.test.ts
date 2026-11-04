import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runScenarioCase} from '../src/runner.js';
import {validateHandoffResult} from '../src/schemas.js';
import type {HandoffResult} from '../src/types.js';

let sequence=0;const ids=()=>`probe-${++sequence}`;
const clock=()=>new Date('2026-09-02T00:00:00.000Z');

test('attribution_present_and_sums_match',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m2-attr-'));
 try{
  const code=await runScenarioCase({mode:'code',caseId:'code-billing-handoff',tracePath:join(tmp,'c.jsonl'),clock,idFactory:ids});
  const model=await runScenarioCase({mode:'model',caseId:'model-technical-handoff',tracePath:join(tmp,'m.jsonl'),clock,idFactory:ids});
  expect(code.attribution).toEqual({steps:[
   {step_name:'classify',latency_ms:30,cost_cents:0,attempts:1},
   {step_name:'receiver.billing-specialist',latency_ms:10,cost_cents:0,attempts:1}],
   totals:{latency_ms:40,cost_cents:0,attempts:2}});
  expect(model.attribution).toEqual({steps:[
   {step_name:'classify',latency_ms:30,cost_cents:2,attempts:1},
   {step_name:'receiver.technical-specialist',latency_ms:11,cost_cents:0,attempts:1}],
   totals:{latency_ms:41,cost_cents:2,attempts:2}});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('attribution_absent_rejected_by_schema',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m2-attr-'));
 try{
  const result:HandoffResult=await runScenarioCase({mode:'code',caseId:'code-billing-handoff',tracePath:join(tmp,'t.jsonl'),clock,idFactory:ids});
  const stripped={...result} as Partial<HandoffResult>;delete stripped.attribution;
  expect(validateHandoffResult(result).ok).toBe(true);
  expect(validateHandoffResult(stripped as HandoffResult).ok).toBe(false);
 } finally{rmSync(tmp,{recursive:true,force:true});}
});
