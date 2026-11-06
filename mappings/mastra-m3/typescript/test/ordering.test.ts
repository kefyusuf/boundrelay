import {describe,expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {BoundedWorkerExecutor,runWorkflow} from '../src/mapping.js';
import {loadCase,loadScenarioProjection,loadWorkersProjection,type RunCase} from '../src/fixtures.js';
import {WORKER_IDS} from '../src/fixtures.js';

const withTempDir=async(fn:(dir:string)=>Promise<void>):Promise<void>=>{
 const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-ord-'));
 try{await fn(dir);}finally{rmSync(dir,{recursive:true,force:true});}
};

const permutedCase=(base:RunCase,order:readonly string[]):RunCase=>({...base,completion_order:order as RunCase['completion_order']});

describe('canonical order and order independence',()=>{
 test('canonical outcome order is invariant under every feasible completion permutation',async()=>{
  await withTempDir(async dir=>{
   const base=loadCase('parallel-complete');
   // Feasible under canonical admission (limit 2): every permutation whose
   // first completer is a first-wave (canonical-prior) worker. The two
   // delivery-status-first permutations would deadlock and trip the guard.
   const feasibleOrders=([['order-details','payment-status','delivery-status'],['payment-status','order-details','delivery-status'],['order-details','delivery-status','payment-status'],['payment-status','delivery-status','order-details']] as const);
   expect(feasibleOrders).toHaveLength(4);
   const briefs=[];
   for(const [index,order] of feasibleOrders.entries()){
    const executor=new BoundedWorkerExecutor(order,2);
    const result=await runWorkflow(permutedCase(base,order),executor,join(dir,`perm-${index}.jsonl`),`run-${index}`);
    expect(result.worker_outcomes.map(o=>o.worker_id)).toEqual([...WORKER_IDS]);
    expect(result.status).toBe('SUCCEEDED');
    briefs.push(result.brief);
   }
   for(const brief of briefs)expect(brief).toEqual(briefs[0]);
  });
 });
 test('the out-of-order fixture case completes in its scripted order yet publishes canonically',async()=>{
  await withTempDir(async dir=>{
   const result=await runWorkflow(loadCase('parallel-out-of-order'),new BoundedWorkerExecutor(['payment-status','delivery-status','order-details'],2),join(dir,'ooo.jsonl'),'r');
   expect(result.worker_outcomes.map(o=>o.worker_id)).toEqual([...WORKER_IDS]);
   expect(result.status).toBe('SUCCEEDED');
   expect(result.brief?.sections.map(s=>s.worker_id)).toEqual([...WORKER_IDS]);
  });
 });
 test('brief sections and missing_workers are canonically ordered under failure',async()=>{
  await withTempDir(async dir=>{
   const base=loadCase('parallel-partial-failure');
   const result=await runWorkflow(permutedCase(base,['payment-status','order-details','delivery-status']),new BoundedWorkerExecutor(['payment-status','order-details','delivery-status'],2),join(dir,'pf.jsonl'),'r');
   expect(result.brief?.sections.map(s=>s.worker_id)).toEqual(['order-details','payment-status']);
   expect(result.brief?.missing_workers).toEqual(['delivery-status']);
  });
 });
 test('the workers projection feeds the instructions unchanged',()=>{
  const workers=loadWorkersProjection();
  const scenario=loadScenarioProjection();
  const spec=scenario.cases.find(c=>c.case_id==='parallel-out-of-order');
  const c=loadCase('parallel-out-of-order');
  expect(spec).toBeDefined();
  expect(workers[spec!.worker_fixture]).toBeDefined();
  expect(c.instructions).toEqual(workers[spec!.worker_fixture]);
 });
});
