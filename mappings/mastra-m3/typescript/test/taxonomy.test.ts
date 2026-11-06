import {describe,expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runCorrected} from '../src/mapping.js';

const withTempTrace=async(fn:(trace:string)=>Promise<void>):Promise<void>=>{
 const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-tax-'));
 try{await fn(join(dir,'trace.jsonl'));}finally{rmSync(dir,{recursive:true,force:true});}
};

describe('M3 failure taxonomy on the Mastra workflow',()=>{
 test('declared worker failure -> WORKER_EXECUTION_FAILED, PARTIAL, synthesis still runs',async()=>{
  await withTempTrace(async trace=>{
   const r=await runCorrected('parallel-partial-failure',trace);
   expect(r.status).toBe('PARTIAL');
   const delivery=r.worker_outcomes.find(o=>o.worker_id==='delivery-status');
   expect(delivery).toEqual({worker_id:'delivery-status',status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'});
   expect(r.brief?.missing_workers).toEqual(['delivery-status']);
   expect(r.synthesis_invoked).toBe(true);
   expect(r.failure_code).toBeNull();
  });
 });
 test('invalid worker output -> INVALID_WORKER_OUTPUT, UNKNOWN never published',async()=>{
  await withTempTrace(async trace=>{
   const r=await runCorrected('parallel-invalid-output',trace);
   expect(r.status).toBe('PARTIAL');
   const payment=r.worker_outcomes.find(o=>o.worker_id==='payment-status');
   expect(payment).toEqual({worker_id:'payment-status',status:'FAILED',output:null,failure_code:'INVALID_WORKER_OUTPUT'});
   expect(JSON.stringify(r)).not.toContain('UNKNOWN');
   expect(r.brief?.sections.map(s=>s.worker_id)).toEqual(['order-details','delivery-status']);
  });
 });
 test('all workers failed -> FAILED / ALL_WORKERS_FAILED, no synthesis',async()=>{
  await withTempTrace(async trace=>{
   const r=await runCorrected('parallel-all-failed',trace);
   expect(r.status).toBe('FAILED');
   expect(r.failure_code).toBe('ALL_WORKERS_FAILED');
   expect(r.synthesis_invoked).toBe(false);
   expect(r.brief).toBeNull();
   expect(r.worker_outcomes.every(o=>o.status==='FAILED'&&o.failure_code==='WORKER_EXECUTION_FAILED')).toBe(true);
  });
 });
 test('declared errors never fail the workflow run itself',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-tax2-'));
  try{
   const runs=[
    await runCorrected('parallel-partial-failure',join(dir,'a.jsonl')),
    await runCorrected('parallel-all-failed',join(dir,'b.jsonl'))];
   expect(runs.map(r=>r.status).sort()).toEqual(['FAILED','PARTIAL']);
  }finally{rmSync(dir,{recursive:true,force:true});}
 });
});
