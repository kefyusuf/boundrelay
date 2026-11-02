import {expect,test} from 'vitest';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {derivePending,resumeRun,replayFrom,type RunOptions} from '../src/recovery.js';
import {StateStore,loadRunState} from '../src/state-store.js';
import {canonicalizeOutcomes} from '../src/collector.js';
import {synthesizeBrief} from '../src/synthesizer.js';
import {WORKER_IDS,type CanonicalOutcomes,type RunStateDocument,type StateBinding,type WorkerDirectory,type WorkerId,type WorkerLifecycle,type WorkerOutput,type WorkerOutcome} from '../src/types.js';
const binding=(caseId:string):StateBinding=>({case_id:caseId,execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2});
const OUTPUTS={['order-details']:{order_id:'ORD-1001',order_status:'SHIPPED'},['payment-status']:{order_id:'ORD-1001',payment_status:'PAID'},['delivery-status']:{order_id:'ORD-1001',delivery_status:'DELIVERED'}} as Record<string,WorkerOutput>;
const succeeded=(id:WorkerId):WorkerOutcome=>({worker_id:id,status:'SUCCEEDED',output:OUTPUTS[id]!,failure_code:null});
const failed=(id:WorkerId):WorkerOutcome=>({worker_id:id,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'});
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m4-rec-'));}
function seedStore(root:string,caseId:string):StateStore {return new StateStore(root,binding(caseId),[...WORKER_IDS]);}
function harness(){
 const entered=new Map<WorkerId,Promise<void>>(),notify=new Map<WorkerId,()=>void>(),gates=new Map<WorkerId,()=>void>();
 const active=new Set<WorkerId>(),log:string[]=[],events:WorkerLifecycle[]=[],counts=Object.fromEntries(WORKER_IDS.map(id=>[id,0]));let peak=0;
 for(const id of WORKER_IDS)entered.set(id,new Promise(r=>notify.set(id,r)));
 const outputs=[OUTPUTS['order-details'],OUTPUTS['payment-status'],OUTPUTS['delivery-status']];
 const directory:WorkerDirectory={resolve:id=>({id,handle:async input=>{
  counts[id]!++;log.push(`enter:${id}`);active.add(id);peak=Math.max(peak,active.size);const gate=new Promise<void>(r=>gates.set(id,r));notify.get(id)!();
  await gate;active.delete(id);return outputs[WORKER_IDS.indexOf(id)];
 }})};
 const control={acknowledgeOutcome:()=>{},beginDrain:()=>{for(const release of gates.values())release();}};
 return {directory,control,entered,log,events,counts,release:(id:WorkerId)=>gates.get(id)!(),peak:()=>peak};
}
function recorder(log?:string[]){
 const events:{type:string;data:Record<string,unknown>}[]=[];
 return {events,emit:(type:string,data:Record<string,unknown>)=>{events.push({type,data});if(type==='checkpoint.restored')log?.push('restored');},restored:()=>events.filter(e=>e.type==='checkpoint.restored')};
}
function baseOptions(overrides:Partial<RunOptions>):RunOptions {
 return {caseId:'parallel-crash-resume',tracePath:'trace.jsonl',stateDir:overrides.stateDir??freshRoot(),...overrides};
}
test('resume_skips_recorded_workers_and_reexecutes_inflight_exactly_once',async()=>{
 const root=freshRoot();const seed=seedStore(root,'parallel-crash-resume');
 seed.markRunning('order-details');seed.recordStepTerminal('order-details',succeeded('order-details'));seed.markRunning('payment-status');
 const h=harness();const sink=recorder(h.log);let syntheses=0;
 const options=baseOptions({stateDir:root,sink,directory:h.directory,control:h.control,synthesizer:(orderId,outcomes)=>{syntheses++;return synthesizeBrief(orderId,outcomes);}});
 const run=resumeRun(options);
 await h.entered.get('payment-status');await h.entered.get('delivery-status');
 h.release('payment-status');h.release('delivery-status');
 const result=await run;
 expect(h.counts['order-details']).toBe(0);expect(h.counts['payment-status']).toBe(1);expect(h.counts['delivery-status']).toBe(1);
 expect(syntheses).toBe(1);expect(result.synthesis_invoked).toBe(true);
 expect(result.status).toBe('SUCCEEDED');expect(result.run_state_status).toBe('SUCCEEDED');
 expect(result.resumed).toBe(true);expect(result.restored_cursor).toBe(1);expect(result.restored_worker_ids).toEqual(['order-details']);
 expect(result.peak_concurrency).toBe(2);expect(result.state_dir).toBe(root);expect(result.failure_code).toBeNull();
 expect(result.brief?.complete).toBe(true);expect(result.brief?.sections).toHaveLength(3);
 expect(sink.restored()).toHaveLength(1);expect(sink.restored()[0]!.data.state_status).toBe('RUNNING');
 expect(h.log[0]).toBe('restored');
 expect(loadRunState(root,binding('parallel-crash-resume')).document.status).toBe('SUCCEEDED');
 rmSync(root,{recursive:true,force:true});
});
test('resume_never_reexecutes_recorded_failures',async()=>{
 const root=freshRoot();const seed=seedStore(root,'parallel-crash-resume');
 for(const id of WORKER_IDS)seed.recordStepTerminal(id,id==='delivery-status'?failed(id):succeeded(id));
 const h=harness();const sink=recorder(h.log);let syntheses=0;let synthesized:CanonicalOutcomes|undefined;
 const options=baseOptions({stateDir:root,sink,directory:h.directory,control:h.control,synthesizer:(orderId,outcomes)=>{syntheses++;synthesized=outcomes;return synthesizeBrief(orderId,outcomes);}});
 const result=await resumeRun(options);
 expect(Object.values(h.counts)).toEqual([0,0,0]);expect(h.log).toEqual(['restored']);
 expect(derivePending(loadRunState(root,binding('parallel-crash-resume')).document)).toEqual([]);
 expect(result.status).toBe('PARTIAL');expect(result.run_state_status).toBe('PARTIAL');
 expect(result.restored_cursor).toBe(3);expect(result.restored_worker_ids).toEqual([...WORKER_IDS]);
 expect(syntheses).toBe(1);expect(result.synthesis_invoked).toBe(true);
 expect(synthesized!.find(o=>o.worker_id==='delivery-status')).toEqual(failed('delivery-status'));
 expect(result.brief?.complete).toBe(false);expect(result.brief?.missing_workers).toEqual(['delivery-status']);
 expect(loadRunState(root,binding('parallel-crash-resume')).document.status).toBe('PARTIAL');
 rmSync(root,{recursive:true,force:true});
});
test('replay_seeds_new_run_without_touching_source',async()=>{
 const root=freshRoot();const source=seedStore(root,'parallel-replay-from-checkpoint');
 source.recordStepTerminal('order-details',succeeded('order-details'));
 const sourceState=source.statePath(),snapshot=source.snapshotPath(1);
 const beforeState=readFileSync(sourceState,'utf8'),beforeSnapshot=readFileSync(snapshot,'utf8');
 const h=harness();const sink=recorder();let syntheses=0;
 const run=replayFrom(snapshot,baseOptions({caseId:'parallel-replay-from-checkpoint',stateDir:root,sink,directory:h.directory,control:h.control,synthesizer:(orderId,outcomes)=>{syntheses++;return synthesizeBrief(orderId,outcomes);}}));
 await h.entered.get('payment-status');await h.entered.get('delivery-status');
 h.release('payment-status');h.release('delivery-status');
 const result=await run;
 expect(result.run_id).not.toBe(source.state().run_id);
 expect(result.status).toBe('SUCCEEDED');expect(result.restored_cursor).toBe(1);expect(result.restored_worker_ids).toEqual(['order-details']);
 expect(h.counts['order-details']).toBe(0);expect(h.counts['payment-status']).toBe(1);expect(h.counts['delivery-status']).toBe(1);
 expect(syntheses).toBe(1);
 expect(result.brief).toEqual(synthesizeBrief('ORD-1001',canonicalizeOutcomes([succeeded('order-details'),succeeded('payment-status'),succeeded('delivery-status')],'ORD-1001')));
 expect(readFileSync(sourceState,'utf8')).toBe(beforeState);expect(readFileSync(snapshot,'utf8')).toBe(beforeSnapshot);
 expect(readFileSync(join(root,result.run_id,'state.json'),'utf8')).toContain(result.run_id);
 rmSync(root,{recursive:true,force:true});
});
test('cancel_resume_completes_remaining_workers_only',async()=>{
 const root=freshRoot();const seed=seedStore(root,'parallel-cancel-resume');
 seed.recordStepTerminal('order-details',succeeded('order-details'));seed.recordStepTerminal('payment-status',succeeded('payment-status'));
 seed.markCancelledFrom('delivery-status');seed.markTerminal('CANCELLED');
 const h=harness();const sink=recorder();
 const run=resumeRun(baseOptions({caseId:'parallel-cancel-resume',stateDir:root,sink,directory:h.directory,control:h.control,synthesizer:synthesizeBrief}));
 await h.entered.get('delivery-status');h.release('delivery-status');
 const result=await run;
 expect(h.counts['delivery-status']).toBe(1);expect(h.counts['order-details']).toBe(0);expect(h.counts['payment-status']).toBe(0);
 expect(result.status).toBe('SUCCEEDED');expect(result.run_state_status).toBe('SUCCEEDED');
 expect(result.restored_cursor).toBe(2);expect(result.restored_worker_ids).toEqual(['order-details','payment-status']);
 expect(result.brief?.complete).toBe(true);expect(sink.restored()[0]!.data.state_status).toBe('CANCELLED');
 const document=loadRunState(root,binding('parallel-cancel-resume')).document;
 expect(document.status).toBe('SUCCEEDED');expect(document.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','SUCCEEDED']);
 rmSync(root,{recursive:true,force:true});
});
test('resume_rejects_binding_mismatch_and_terminal_states_without_invocations',async()=>{
 const root=freshRoot();const seed=seedStore(root,'parallel-crash-resume');
 seed.recordStepTerminal('order-details',succeeded('order-details'));
 const h=harness();const sink=recorder();
 await expect(resumeRun(baseOptions({caseId:'parallel-cancel-resume',stateDir:root,sink,directory:h.directory,control:h.control}))).rejects.toThrow('BINDING_MISMATCH');
 expect(Object.values(h.counts)).toEqual([0,0,0]);
 const doneRoot=freshRoot();const done=seedStore(doneRoot,'parallel-crash-resume');
 for(const id of WORKER_IDS)done.recordStepTerminal(id,succeeded(id));
 done.markTerminal('SUCCEEDED');
 const h2=harness();
 await expect(resumeRun(baseOptions({stateDir:doneRoot,sink,directory:h2.directory,control:h2.control}))).rejects.toThrow('not resumable');
 expect(Object.values(h2.counts)).toEqual([0,0,0]);
 rmSync(root,{recursive:true,force:true});rmSync(doneRoot,{recursive:true,force:true});
});
