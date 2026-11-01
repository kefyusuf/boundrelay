import {expect,test} from 'vitest';
import {executeWorkers} from '../src/executor.js';
import {loadScenario} from '../src/scenario.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
import {createWorkerDirectory} from '../src/workers.js';
import {WORKER_IDS,type WorkerId,type WorkerDirectory,type WorkerLifecycle} from '../src/types.js';
function harness(){
 const entered=new Map<WorkerId,Promise<void>>(),notify=new Map<WorkerId,()=>void>(),gates=new Map<WorkerId,()=>void>();
 const active=new Set<WorkerId>(),inputs:unknown[]=[],events:WorkerLifecycle[]=[],counts=Object.fromEntries(WORKER_IDS.map(id=>[id,0]));let peak=0,drains=0;
 for(const id of WORKER_IDS)entered.set(id,new Promise(r=>notify.set(id,r)));
 const outputs=[{order_id:'ORD-1001',order_status:'SHIPPED'},{order_id:'ORD-1001',payment_status:'PAID'},{order_id:'ORD-1001',delivery_status:'DELAYED'}];
 const directory:WorkerDirectory={resolve:id=>({id,handle:async input=>{
  counts[id]!++;inputs.push(input);expect(Object.isFrozen(input)).toBe(true);expect(Object.keys(input)).toEqual(['order_id']);
  active.add(id);peak=Math.max(peak,active.size);const gate=new Promise<void>(r=>gates.set(id,r));notify.get(id)!();
  await gate;active.delete(id);return outputs[WORKER_IDS.indexOf(id)];
 }})};
 const control={acknowledgeOutcome:()=>{},beginDrain:()=>{drains++;for(const release of gates.values())release();}};
 return {directory,control,active,entered,inputs,events,counts,release:(id:WorkerId)=>gates.get(id)!(),peak:()=>peak,drains:()=>drains};
}
const input={order_id:'ORD-1001'};
test('parallel_calls_overlap_without_exceeding_two',async()=>{
 const h=harness();const run=executeWorkers({mode:'parallel',input,directory:h.directory,control:h.control,observer:e=>h.events.push(e)});
 await Promise.all([h.entered.get('order-details'),h.entered.get('payment-status')]);
 expect([...h.active]).toEqual(['order-details','payment-status']);expect(h.counts['delivery-status']).toBe(0);
 h.release('payment-status');await h.entered.get('delivery-status');expect(h.active.has('order-details')).toBe(true);
 expect(h.events.filter(e=>e.kind==='terminal').map(e=>e.outcome.worker_id)).toEqual(['payment-status']);
 h.release('delivery-status');h.release('order-details');const result=await run;
 expect(h.peak()).toBe(2);expect(result.peakConcurrency).toBe(2);expect(Object.values(h.counts)).toEqual([1,1,1]);
 expect(new Set(h.inputs).size).toBe(3);expect(h.inputs.every(i=>i!==input)).toBe(true);expect(input.order_id).toBe('ORD-1001');
});
test('sequential_never_overlaps',async()=>{
 const h=harness();const run=executeWorkers({mode:'sequential',input,directory:h.directory,control:h.control,observer:e=>h.events.push(e)});
 for(const id of WORKER_IDS){await h.entered.get(id);expect([...h.active]).toEqual([id]);h.release(id);}
 expect((await run).peakConcurrency).toBe(1);expect(h.peak()).toBe(1);expect(Object.values(h.counts)).toEqual([1,1,1]);
});
test('declared_failures_do_not_retry',async()=>{
 const s=loadScenario();for(const name of ['parallel-partial-failure','parallel-all-failed','parallel-invalid-output']){
 const provider=new ScriptedWorkers(s.cases.find(c=>c.case_id===name)!,s.order_id);const counts=new Map<WorkerId,number>();
 const directory=createWorkerDirectory({...provider,read:async(id,i)=>{counts.set(id,(counts.get(id)??0)+1);return provider.read(id,i);},acknowledgeOutcome:id=>provider.acknowledgeOutcome(id),beginDrain:()=>provider.beginDrain()});
 const result=await executeWorkers({mode:'parallel',input,directory,control:provider,observer:()=>{}});
 expect([...counts.values()]).toEqual([1,1,1]);expect(result.outcomes.filter(o=>o.status==='FAILED')).toHaveLength(name==='parallel-all-failed'?3:1);
 if(name==='parallel-invalid-output')expect(result.outcomes.find(o=>o.worker_id==='payment-status')?.failure_code).toBe('INVALID_WORKER_OUTPUT');
 }
});
test('unexpected_error_drains_without_admitting_queued_worker',async()=>{
 const h=harness();const fatal=new Error('unexpected');const original=h.directory.resolve.bind(h.directory);
 h.directory.resolve=id=>{const worker=original(id)!;return {...worker,handle:async i=>{const value=await worker.handle(i);if(id==='order-details')throw fatal;return value;}};};
 const run=executeWorkers({mode:'parallel',input,directory:h.directory,control:h.control,observer:e=>h.events.push(e)}).then(()=>null,e=>e);
 await h.entered.get('payment-status');h.release('order-details');expect(await run).toBe(fatal);
 expect(h.drains()).toBe(1);expect(h.active.size).toBe(0);expect(h.counts['delivery-status']).toBe(0);
 expect(h.events.filter(e=>e.kind==='terminal'&&e.outcome.worker_id==='order-details')).toHaveLength(0);
});
