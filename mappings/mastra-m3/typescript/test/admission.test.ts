import {describe,expect,test} from 'vitest';
import {BoundedWorkerExecutor,ToolingInterrupted,runCorrected,runWorkflow} from '../src/mapping.js';
import {loadCase,type RunCase} from '../src/fixtures.js';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const withTempDir=async(fn:(dir:string)=>Promise<void>):Promise<void>=>{
 const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-adm-'));
 try{await fn(dir);}finally{rmSync(dir,{recursive:true,force:true});}
};

describe('bounded admission (the mapping centerpiece finding)',()=>{
 test('the corrected workflow reports the deterministic capped peaks 2 (parallel) and 1 (sequential)',async()=>{
  await withTempDir(async dir=>{
   expect((await runCorrected('parallel-complete',join(dir,'a.jsonl'))).peak_concurrency).toBe(2);
   expect((await runCorrected('parallel-out-of-order',join(dir,'b.jsonl'))).peak_concurrency).toBe(2);
   expect((await runCorrected('parallel-partial-failure',join(dir,'c.jsonl'))).peak_concurrency).toBe(2);
   expect((await runCorrected('sequential-complete',join(dir,'d.jsonl'))).peak_concurrency).toBe(1);
  });
 });
 test('the cap binds: the first release waits for the whole first wave (entered >= limit)',async()=>{
  await withTempDir(async dir=>{
   const executor=new BoundedWorkerExecutor(['order-details','payment-status','delivery-status'],2);
   const seen:number[]=[];
   const original=executor.awaitRelease.bind(executor);
   executor.awaitRelease=async(id:string)=>{await original(id);seen.push(executor.observedPeak);};
   await runWorkflow(loadCase('parallel-complete'),executor,join(dir,'bind.jsonl'),'r');
   expect(seen.every(peak=>peak>=2)).toBe(true);
   expect(executor.observedPeak).toBe(2);
  });
 });
 test('the executor admits at most `limit` and frees slots on record',async()=>{
  const executor=new BoundedWorkerExecutor(['a','b','c'],2);
  await executor.enter('a');
  await executor.enter('b');
  let cAdmitted=false;
  const third=executor.enter('c').then(()=>{cAdmitted=true;});
  await Promise.resolve();
  expect(cAdmitted).toBe(false);
  executor.record('a');
  await third;
  expect(cAdmitted).toBe(true);
  expect(executor.observedPeak).toBe(2);
 });
 test('an unexpected error abandons the run: every waiter fails fast instead of hanging',async()=>{
  const executor=new BoundedWorkerExecutor(['a','b','c'],1,{guardMs:150});
  await executor.enter('a');
  const waiter=executor.enter('b');
  executor.abandon('a');
  await expect(waiter).rejects.toThrow(ToolingInterrupted);
 });
 test('an infeasible completion schedule trips the deadlock guard instead of hanging',async()=>{
  await withTempDir(async dir=>{
   const base=loadCase('parallel-complete');
   const infeasible:RunCase={...base,completion_order:['delivery-status','order-details','payment-status']};
   const executor=new BoundedWorkerExecutor(infeasible.completion_order,2,{guardMs:250});
   await expect(runWorkflow(infeasible,executor,join(dir,'dead.jsonl'),'r')).rejects.toThrow(/Admission guard tripped/);
  });
 });
 test('admission limits outside 1..2 are rejected',()=>{
  expect(()=>new BoundedWorkerExecutor(['a','b','c'],3)).toThrow(/1 or 2/);
 });
});
