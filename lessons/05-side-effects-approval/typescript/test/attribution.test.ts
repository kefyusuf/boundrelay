import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runCase} from '../src/runner.js';
import {validateRunResult} from '../src/schemas.js';
import type {RunResult} from '../src/types.js';

class CrashSignal extends Error {}

const WORKER_STEPS=[
 {step_name:'worker.order-details',latency_ms:10,cost_cents:0,attempts:1},
 {step_name:'worker.payment-status',latency_ms:11,cost_cents:0,attempts:1},
 {step_name:'worker.delivery-status',latency_ms:12,cost_cents:0,attempts:1}];
const EFFECT_STEP={step_name:'effect.submit',latency_ms:40,cost_cents:25,attempts:1};

test('rejected_approval_omits_the_effect_step_record',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m5-attr-'));
 try{
  const result=await runCase({caseId:'approval-rejected-no-effect',tracePath:join(tmp,'t.jsonl'),stateDir:join(tmp,'state')});
  expect(result.attribution).toEqual({steps:WORKER_STEPS,totals:{latency_ms:33,cost_cents:0,attempts:3}});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('submit_window_resume_counts_the_original_attempt_once',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m5-attr-'));
 try{
  const on_crash=():never=>{throw new CrashSignal('crash');};
  await expect(runCase({caseId:'crash-submit-window-resolved',tracePath:join(tmp,'crash.jsonl'),stateDir:join(tmp,'state'),on_crash})).rejects.toThrow(CrashSignal);
  const result=await runCase({caseId:'crash-submit-window-resolved',tracePath:join(tmp,'resume.jsonl'),stateDir:join(tmp,'state'),resume:true});
  expect(result.reconciled).toBe(true);
  expect(result.attribution).toEqual({steps:[...WORKER_STEPS,EFFECT_STEP],totals:{latency_ms:73,cost_cents:25,attempts:4}});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('attribution_absent_rejected_by_schema',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m5-attr-'));
 try{
  const result:RunResult=await runCase({caseId:'approval-granted-effect-once',tracePath:join(tmp,'t.jsonl'),stateDir:join(tmp,'state')});
  expect(result.attribution.totals).toEqual({latency_ms:73,cost_cents:25,attempts:4});
  const stripped={...result} as Partial<RunResult>;delete stripped.attribution;
  expect(validateRunResult(result)).toBe(true);
  expect(validateRunResult(stripped as RunResult)).toBe(false);
 } finally{rmSync(tmp,{recursive:true,force:true});}
});
