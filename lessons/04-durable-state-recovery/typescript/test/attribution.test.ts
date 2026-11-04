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

test('crash_resume_reconciles_attempts_across_phases',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m4-attr-'));
 try{
  // crash_after fires after the worker's outcome is recorded, so the resumed
  // run re-executes only the pending worker: attempts [1,1,1].
  const on_crash=():never=>{throw new CrashSignal('crash');};
  await expect(runCase({caseId:'parallel-crash-resume',tracePath:join(tmp,'crash.jsonl'),stateDir:join(tmp,'state'),on_crash})).rejects.toThrow(CrashSignal);
  const result=await runCase({caseId:'parallel-crash-resume',tracePath:join(tmp,'resume.jsonl'),stateDir:join(tmp,'state'),resume:true});
  expect(result.attribution).toEqual({steps:[
   ...WORKER_STEPS,{step_name:'synthesize',latency_ms:15,cost_cents:0,attempts:1}],
   totals:{latency_ms:48,cost_cents:0,attempts:4}});
 } finally{rmSync(tmp,{recursive:true,force:true});}
});

test('fresh_run_single_attempts_and_schema_rejects_absent_attribution',async ()=>{
 const tmp=mkdtempSync(join(tmpdir(),'m4-attr-'));
 try{
  const result:RunResult=await runCase({caseId:'parallel-clean-complete',tracePath:join(tmp,'t.jsonl'),stateDir:join(tmp,'state')});
  expect(result.attribution.totals).toEqual({latency_ms:48,cost_cents:0,attempts:4});
  const stripped={...result} as Partial<RunResult>;delete stripped.attribution;
  expect(validateRunResult(result)).toBe(true);
  expect(validateRunResult(stripped as RunResult)).toBe(false);
 } finally{rmSync(tmp,{recursive:true,force:true});}
});
