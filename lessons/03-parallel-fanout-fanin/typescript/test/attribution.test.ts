import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runCase} from '../src/runner.js';
import {validateRunResult} from '../src/schemas.js';
import type {RunResult} from '../src/types.js';

test('attribution_present_and_sums_match',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m3-attr-'));
 try{
  const complete=await runCase({caseId:'parallel-complete',tracePath:join(tmp,'c.jsonl')});
  const failed=await runCase({caseId:'parallel-all-failed',tracePath:join(tmp,'f.jsonl')});
  expect(complete.attribution).toEqual({steps:[
   {step_name:'worker.order-details',latency_ms:10,cost_cents:0,attempts:1},
   {step_name:'worker.payment-status',latency_ms:11,cost_cents:0,attempts:1},
   {step_name:'worker.delivery-status',latency_ms:12,cost_cents:0,attempts:1},
   {step_name:'synthesize',latency_ms:15,cost_cents:0,attempts:1}],
   totals:{latency_ms:48,cost_cents:0,attempts:4}});
  expect(failed.attribution).toEqual({steps:[
   {step_name:'worker.order-details',latency_ms:10,cost_cents:0,attempts:1},
   {step_name:'worker.payment-status',latency_ms:11,cost_cents:0,attempts:1},
   {step_name:'worker.delivery-status',latency_ms:12,cost_cents:0,attempts:1}],
   totals:{latency_ms:33,cost_cents:0,attempts:3}});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('attribution_absent_rejected_by_schema',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m3-attr-'));
 try{
  const result:RunResult=await runCase({caseId:'parallel-complete',tracePath:join(tmp,'t.jsonl')});
  const stripped={...result} as Partial<RunResult>;delete stripped.attribution;
  expect(validateRunResult(result)).toBe(true);
  expect(validateRunResult(stripped as RunResult)).toBe(false);
 } finally{rmSync(tmp,{recursive:true,force:true});}
});
