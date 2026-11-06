import {describe,expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runNaive} from '../src/naive.js';
import {validateResult} from '../src/results.js';
import {loadCase,type RunCase} from '../src/fixtures.js';

const withTempTrace=async(fn:(trace:string)=>Promise<void>):Promise<void>=>{
 const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-naive-'));
 try{await fn(join(dir,'naive.jsonl'));}finally{rmSync(dir,{recursive:true,force:true});}
};

const naiveCaseWith=(base:RunCase,order:readonly string[]):RunCase=>({...base,completion_order:order as RunCase['completion_order']});

describe('the naive regression: what Mastra defaults produce uncapped',()=>{
 test('uncapped parallel dispatch overlaps all three workers (3-way rendezvous, peak 3)',async()=>{
  await withTempTrace(async trace=>{
   const result=await runNaive('parallel-complete',trace);
   expect(result.peak_concurrency).toBe(3);
   expect(result.concurrency_limit).toBeNull();
   expect(result.status).toBe('SUCCEEDED');
  });
 });
 test('naive sections ignore the scripted completion order (no completion-order semantics)',async()=>{
  await withTempTrace(async trace=>{
   // parallel-out-of-order scripts completion [payment-status,
   // delivery-status, order-details]; the naive graph, with no gates and
   // no canonical collector, publishes whatever order the engine's
   // composition dictates (step-definition order) - the scripted order
   // is not honored anywhere in the result.
   const result=await runNaive('parallel-out-of-order',trace);
   expect(result.worker_outcomes.map(o=>o.worker_id)).toEqual(['order-details','payment-status','delivery-status']);
   expect(result.worker_outcomes.map(o=>o.worker_id)).not.toEqual(['payment-status','delivery-status','order-details']);
  });
 });
 test('invalid outputs are published as facts and the naive result fails the closed schema',async()=>{
  await withTempTrace(async trace=>{
   const result=await runNaive('parallel-invalid-output',trace);
   expect(JSON.stringify(result)).toContain('UNKNOWN');
   expect(validateResult(result)).toBe(false);
  });
 });
 test('declared worker errors propagate and crash the whole naive run (trace prefix flushed)',async()=>{
  await withTempTrace(async trace=>{
   const {readFileSync}=await import('node:fs');
   await expect(runNaive('parallel-partial-failure',trace)).rejects.toThrow(/Declared worker failure/);
   const chunks=readFileSync(trace,'utf8').trim().split('\n').map(line=>JSON.parse(line) as {type:string});
   expect(chunks[0]?.type).toBe('workflow-start');
   expect(chunks.some(c=>c.type==='workflow-step-start')).toBe(true);
  });
 });
 test('the naive all-failed run also crashes (default propagation)',async()=>{
  await withTempTrace(async trace=>{
   await expect(runNaive('parallel-all-failed',trace)).rejects.toThrow(/Declared worker failure/);
  });
 });
 test('the naive result is invariant under the completion order (the order is not a semantics it owns)',async()=>{
  await withTempTrace(async trace=>{
   const {runNaiveCase}=await import('../src/naive.js');
   const base=loadCase('parallel-complete');
   const result=await runNaiveCase(naiveCaseWith(base,['payment-status','order-details','delivery-status']),trace);
   expect(result.worker_outcomes.map(o=>o.worker_id)).toEqual(['order-details','payment-status','delivery-status']);
  });
 });
});
