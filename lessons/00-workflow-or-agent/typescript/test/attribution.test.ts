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
 const tmp=mkdtempSync(join(tmpdir(),'m0-attr-'));
 try{
  const deterministic=await runScenarioCase({mode:'deterministic',caseId:'billing-duplicate-charge',tracePath:join(tmp,'d.jsonl'),clock,idFactory:ids});
  const model=await runScenarioCase({mode:'model',caseId:'billing-duplicate-charge',tracePath:join(tmp,'m.jsonl'),clock,idFactory:ids});
  expect(deterministic.attribution).toEqual({steps:[
   {step_name:'classify',latency_ms:30,cost_cents:0,attempts:1},
   {step_name:'specialist.billing',latency_ms:10,cost_cents:0,attempts:1}],
   totals:{latency_ms:40,cost_cents:0,attempts:2}});
  expect(model.attribution.steps[0]).toEqual({step_name:'classify',latency_ms:30,cost_cents:2,attempts:1});
  expect(model.attribution.totals).toEqual({latency_ms:40,cost_cents:2,attempts:2});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('attribution_absent_rejected_by_schema',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m0-attr-'));
 try{
  const result:RunResult=await runScenarioCase({mode:'model',caseId:'billing-duplicate-charge',tracePath:join(tmp,'t.jsonl'),clock,idFactory:ids});
  const stripped={...result} as Partial<RunResult>;delete stripped.attribution;
  expect(validateRunResult(result).ok).toBe(true);
  expect(validateRunResult(stripped as RunResult).ok).toBe(false);
 } finally{rmSync(tmp,{recursive:true,force:true});}
});
