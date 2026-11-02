import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join} from 'node:path';
import {executeWorkers} from '../src/executor.js';
import {resumeRun} from '../src/recovery.js';
import {loadScenario} from '../src/scenario.js';
import {StateStore} from '../src/state-store.js';
import {WORKER_IDS,type WorkerDirectory,type WorkerId,type WorkerOutput} from '../src/types.js';

const OUTPUTS:Record<WorkerId,WorkerOutput>={'order-details':{order_id:'ORD-1001',order_status:'SHIPPED'},'payment-status':{order_id:'ORD-1001',payment_status:'PAID'},'delivery-status':{order_id:'ORD-1001',delivery_status:'DELAYED'}};
test('retry_without_state_duplicates_every_invocation',async()=>{
 const scenario=loadScenario();const spec=scenario.cases.find(c=>c.case_id==='parallel-clean-complete')!;
 const binding={case_id:spec.case_id,execution_mode:'parallel' as const,requested_order_id:scenario.order_id,concurrency_limit:2 as const};
 const root=mkdtempSync(join(tmpdir(),'br-m4-naive-'));
 try{
  const store=new StateStore(root,binding,[...WORKER_IDS]);
  store.recordStepTerminal('order-details',{worker_id:'order-details',status:'SUCCEEDED',output:structuredClone(OUTPUTS['order-details']),failure_code:null});
  const counts:Record<WorkerId,number>={'order-details':0,'payment-status':0,'delivery-status':0};
  const counting={acknowledgeOutcome:()=>{},beginDrain:()=>{}};
  const directory:WorkerDirectory={resolve:id=>({id,handle:async()=>{counts[id]+=1;return structuredClone(OUTPUTS[id]);}})};
  const naive=await executeWorkers({mode:'parallel',input:{order_id:scenario.order_id},directory,control:counting,observer:()=>{}});
  const naiveCounts=WORKER_IDS.map(id=>counts[id]);
  expect(naiveCounts).toEqual([1,1,1]);
  const resumed=await resumeRun({caseId:'parallel-clean-complete',tracePath:'naive.jsonl',stateDir:root,sink:{emit:()=>{}},directory,control:counting});
  const resumeCounts=WORKER_IDS.map(id=>counts[id]);
  expect(resumeCounts).toEqual([1,2,2]);
  expect(resumed.status).toBe('SUCCEEDED');
  expect(resumed.resumed).toBe(true);
  expect(resumed.restored_worker_ids).toEqual(['order-details']);
  expect(naiveCounts.reduce((a,b)=>a+b,0)+1).toBe(4);
  expect(resumeCounts.reduce((a,b)=>a+b,0)-naiveCounts.reduce((a,b)=>a+b,0)).toBe(2);
  expect(naive.outcomes.filter(o=>o.status==='SUCCEEDED')).toHaveLength(3);
 }finally{rmSync(root,{recursive:true,force:true});}
});
