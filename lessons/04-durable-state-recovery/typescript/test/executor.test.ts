import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {CrashSignal,executeWorkers} from '../src/executor.js';
import {StateStore,loadRunState} from '../src/state-store.js';
import {loadScenario} from '../src/scenario.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
import {createWorkerDirectory} from '../src/workers.js';
import {WORKER_IDS,type CaseSpec,type RecoveryControls,type RunStateDocument,type StateBinding,type WorkerDirectory,type WorkerId,type WorkerLifecycle,type WorkerProvider} from '../src/types.js';
const input={order_id:'ORD-1001'};
const binding=(caseId:string):StateBinding=>({case_id:caseId,execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2});
function freshStore(caseId:string):{store:StateStore;root:string} {
 const root=mkdtempSync(join(tmpdir(),'br-m4-exec-'));
 return {store:new StateStore(root,binding(caseId),[...WORKER_IDS]),root};
}
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
function providerHarness(provider:WorkerProvider){
 const counts=new Map<WorkerId,number>(WORKER_IDS.map(id=>[id,0] as [WorkerId,number]));let drains=0;
 const directory=createWorkerDirectory({...provider,read:async(id,i)=>{counts.set(id,(counts.get(id)??0)+1);return provider.read(id,i);},acknowledgeOutcome:id=>provider.acknowledgeOutcome(id),beginDrain:()=>{drains++;provider.beginDrain();}});
 return {directory,counts,drains:()=>drains};
}
test('parallel_calls_overlap_without_exceeding_two',async()=>{
 const h=harness();const {store,root}=freshStore('probe-parallel');
 const run=executeWorkers({mode:'parallel',input,directory:h.directory,control:h.control,observer:e=>h.events.push(e),store});
 await Promise.all([h.entered.get('order-details'),h.entered.get('payment-status')]);
 expect([...h.active]).toEqual(['order-details','payment-status']);expect(h.counts['delivery-status']).toBe(0);
 expect(store.state().steps.map(s=>s.status)).toEqual(['RUNNING','RUNNING','PENDING']);
 h.release('payment-status');await h.entered.get('delivery-status');expect(h.active.has('order-details')).toBe(true);
 expect(h.events.filter(e=>e.kind==='terminal').map(e=>e.outcome.worker_id)).toEqual(['payment-status']);
 expect(store.state().sequence_cursor).toBe(1);expect(store.state().steps[1]!.status).toBe('SUCCEEDED');
 h.release('delivery-status');h.release('order-details');const result=await run;
 expect(h.peak()).toBe(2);expect(result.peakConcurrency).toBe(2);expect(Object.values(h.counts)).toEqual([1,1,1]);
 expect(new Set(h.inputs).size).toBe(3);expect(h.inputs.every(i=>i!==input)).toBe(true);expect(input.order_id).toBe('ORD-1001');
 expect(store.state().sequence_cursor).toBe(3);expect(store.state().steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','SUCCEEDED']);
 rmSync(root,{recursive:true,force:true});
});
test('sequential_never_overlaps',async()=>{
 const h=harness();const {store,root}=freshStore('probe-sequential');
 const run=executeWorkers({mode:'sequential',input,directory:h.directory,control:h.control,observer:e=>h.events.push(e),store});
 for(const id of WORKER_IDS){await h.entered.get(id);expect([...h.active]).toEqual([id]);h.release(id);}
 expect((await run).peakConcurrency).toBe(1);expect(h.peak()).toBe(1);expect(Object.values(h.counts)).toEqual([1,1,1]);
 expect(store.state().sequence_cursor).toBe(3);expect(store.state().steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','SUCCEEDED']);
 rmSync(root,{recursive:true,force:true});
});
test('declared_failures_do_not_retry',async()=>{
 for(const name of ['partial-failure','all-failed','invalid-output']){
  const spec:CaseSpec={case_id:`probe-${name}`,execution_mode:'parallel',worker_fixture:`fixtures/workers/order-brief/${name}.yaml`,completion_order:[...WORKER_IDS]};
  const provider=new ScriptedWorkers(spec,'ORD-1001');const {directory,counts}=providerHarness(provider);
  const {store,root}=freshStore(spec.case_id);
  const result=await executeWorkers({mode:'parallel',input,directory,control:provider,observer:()=>{},store});
  expect([...counts.values()]).toEqual([1,1,1]);
  expect(result.outcomes.filter(o=>o.status==='FAILED')).toHaveLength(name==='all-failed'?3:1);
  if(name==='invalid-output')expect(result.outcomes.find(o=>o.worker_id==='payment-status')?.failure_code).toBe('INVALID_WORKER_OUTPUT');
  const doc=store.state();
  expect(doc.sequence_cursor).toBe(3);expect(doc.steps.every(s=>s.status==='SUCCEEDED'||s.status==='FAILED')).toBe(true);
  const expectedCode=name==='invalid-output'?'INVALID_WORKER_OUTPUT':name==='all-failed'?'WORKER_EXECUTION_FAILED':null;
  expect(doc.steps.find(s=>s.worker_id==='payment-status')!.failure_code).toBe(expectedCode);
  rmSync(root,{recursive:true,force:true});
 }
});
test('unexpected_error_drains_without_admitting_queued_worker',async()=>{
 const h=harness();const {store,root}=freshStore('probe-fatal');
 const fatal=new Error('unexpected');const original=h.directory.resolve.bind(h.directory);
 h.directory.resolve=id=>{const worker=original(id)!;return {...worker,handle:async i=>{const value=await worker.handle(i);if(id==='order-details')throw fatal;return value;}};};
 const run=executeWorkers({mode:'parallel',input,directory:h.directory,control:h.control,observer:e=>h.events.push(e),store}).then(()=>null,e=>e);
 await h.entered.get('payment-status');h.release('order-details');expect(await run).toBe(fatal);
 expect(h.drains()).toBe(1);expect(h.active.size).toBe(0);expect(h.counts['delivery-status']).toBe(0);
 expect(h.events.filter(e=>e.kind==='terminal'&&e.outcome.worker_id==='order-details')).toHaveLength(0);
 expect(store.state().sequence_cursor).toBe(0);expect(store.state().steps.map(s=>s.status)).toEqual(['RUNNING','RUNNING','PENDING']);
 rmSync(root,{recursive:true,force:true});
});
test('cancel_before_stops_admission_and_records_drained_terminals',async()=>{
 const s=loadScenario();const spec=s.cases.find(c=>c.case_id==='parallel-cancel-resume')!;
 const provider=new ScriptedWorkers(spec,s.order_id);const {directory,counts,drains}=providerHarness(provider);
 const {store,root}=freshStore('parallel-cancel-resume');
 const controls:RecoveryControls={cancel_before:'delivery-status'};
 const summary=await executeWorkers({mode:'parallel',input,directory,control:provider,observer:()=>{},store,controls,completion_order:[...spec.completion_order]});
 expect(summary.cancelled_before).toBe('delivery-status');
 expect(summary.outcomes.map(o=>o.worker_id)).toEqual(['order-details','payment-status']);
 expect(summary.peakConcurrency).toBe(2);expect(drains()).toBe(0);expect([...counts.values()]).toEqual([1,1,0]);
 const doc=store.state();
 expect(doc.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','PENDING']);
 expect(doc.sequence_cursor).toBe(2);expect(doc.status).toBe('RUNNING');
 rmSync(root,{recursive:true,force:true});
});
test('crash_after_requires_quiescent_boundary',async()=>{
 const s=loadScenario();const spec=s.cases.find(c=>c.case_id==='parallel-crash-resume')!;
 const provider=new ScriptedWorkers(spec,s.order_id);const {directory,counts,drains}=providerHarness(provider);
 const {store,root}=freshStore('parallel-crash-resume');
 let crashes=0;let atCrash:RunStateDocument|undefined;
 const run=executeWorkers({mode:'parallel',input,directory,control:provider,observer:()=>{},store,controls:{crash_after:'payment-status'},completion_order:[...spec.completion_order],on_crash:()=>{crashes++;atCrash=store.state();throw new CrashSignal('crash');}}).then(()=>null,e=>e);
 expect(await run).toBeInstanceOf(CrashSignal);
 expect(crashes).toBe(1);expect(drains()).toBe(0);expect([...counts.values()]).toEqual([1,1,0]);
 expect(atCrash!.status).toBe('RUNNING');expect(atCrash!.sequence_cursor).toBe(2);
 expect(atCrash!.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','PENDING']);
 expect(loadRunState(root,binding('parallel-crash-resume')).document.sequence_cursor).toBe(2);
 rmSync(root,{recursive:true,force:true});
});
test('crash_after_fires_after_recorded_failure',async()=>{
 const s=loadScenario();const spec=s.cases.find(c=>c.case_id==='parallel-crash-resume-partial')!;
 const provider=new ScriptedWorkers(spec,s.order_id);const {directory,counts,drains}=providerHarness(provider);
 const {store,root}=freshStore('parallel-crash-resume-partial');
 let crashes=0;let atCrash:RunStateDocument|undefined;
 const run=executeWorkers({mode:'parallel',input,directory,control:provider,observer:()=>{},store,controls:{crash_after:'delivery-status'},completion_order:[...spec.completion_order],on_crash:()=>{crashes++;atCrash=store.state();throw new CrashSignal('crash');}}).then(()=>null,e=>e);
 expect(await run).toBeInstanceOf(CrashSignal);
 expect(crashes).toBe(1);expect(drains()).toBe(0);expect([...counts.values()]).toEqual([1,1,1]);
 expect(atCrash!.status).toBe('RUNNING');expect(atCrash!.sequence_cursor).toBe(3);
 expect(atCrash!.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','FAILED']);
 expect(atCrash!.steps[2]!.failure_code).toBe('WORKER_EXECUTION_FAILED');
 rmSync(root,{recursive:true,force:true});
});
