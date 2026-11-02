import {expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {CrashSignal,executeWorkers} from '../src/executor.js';
import {StateStore} from '../src/state-store.js';
import {EffectLedger} from '../src/effect-ledger.js';
import {AuditWriter} from '../src/audit.js';
import {ApprovalGate} from '../src/approval.js';
import {effectDigest,effectKey} from '../src/idempotency.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
import {createWorkerDirectory} from '../src/workers.js';
import {WORKER_IDS,type CaseSpec,type EffectConfirmation,type EffectPayload,type EffectSink,type EffectWiring,type AuditSink,type RecoveryControls,type StateStore as StoreApi,type WorkerId,type WorkerOutcome,type WorkerProvider} from '../src/types.js';
const PAYLOAD:EffectPayload={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'};
const KEY=effectKey(PAYLOAD),DIGEST=effectDigest(PAYLOAD);
const CONFIRMED:EffectConfirmation={key:KEY,payload_digest:DIGEST,status:'EFFECT_COMPLETED',outcome:{refund_id:'RFL-1001',refunded_at:'2026-11-02T00:00:00Z'},duplicate:false};
function probe(decision:'granted'|'rejected',opts:{fixture?:string;controls?:RecoveryControls}={}){
 const root=mkdtempSync(join(tmpdir(),'br-m5-exec-'));
 const spec:CaseSpec={case_id:'probe',execution_mode:'parallel',worker_fixture:`fixtures/workers/order-brief/${opts.fixture??'complete'}.yaml`,completion_order:[...WORKER_IDS],approval:{decision:'granted',approver:'approver-primary'}};
 const provider=new ScriptedWorkers(spec,'ORD-1001');
 const counts=new Map<WorkerId,number>(WORKER_IDS.map(id=>[id,0] as [WorkerId,number]));
 const active=new Set<WorkerId>();let peak=0,drains=0,crashes=0;
 const wrapped:WorkerProvider={read:async(id,i)=>{counts.set(id,(counts.get(id)??0)+1);active.add(id);peak=Math.max(peak,active.size);try{return await provider.read(id,i);}finally{active.delete(id);}},
  acknowledgeOutcome:id=>provider.acknowledgeOutcome(id),beginDrain:()=>{drains++;provider.beginDrain();}};
 const directory=createWorkerDirectory(wrapped);
 const events:string[]=[];
 const realStore=new StateStore(root,{case_id:'probe',execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2},[...WORKER_IDS]);
 const store:StoreApi={markRunning:id=>{events.push(`start:${id}`);realStore.markRunning(id);},
  recordStepTerminal:(id,o)=>{events.push(`terminal:${id}`);realStore.recordStepTerminal(id,o);},
  markCancelledFrom:id=>realStore.markCancelledFrom(id),markTerminal:(s,f)=>realStore.markTerminal(s,f),
  markSubmitted:(k,d)=>{events.push('marker');realStore.markSubmitted(k,d);},
  recordEffectOutcome:e=>{events.push('store-effect');realStore.recordEffectOutcome(e);},
  state:()=>realStore.state(),statePath:()=>realStore.statePath(),snapshotPath:s=>realStore.snapshotPath(s)};
 const realLedger=new EffectLedger(root);
 const ledger:EffectSink={submit:(k,d,p)=>{events.push('submit');return realLedger.submit(k,d,p);},lookup:k=>realLedger.lookup(k)};
 const realAudit=new AuditWriter(root);
 const audit:AuditSink={append:r=>{events.push(r.kind==='approval'?'audit-approval':'audit-effect');realAudit.append(r);}};
 const wiring:EffectWiring={ledger,approvalGate:new ApprovalGate({decision,approver:'approver-primary'}),audit,
  controls:opts.controls,on_crash:()=>{crashes++;events.push('crash');throw new CrashSignal('crash');}};
 const run=()=>executeWorkers({mode:'parallel',input:{order_id:'ORD-1001'},directory,control:wrapped,observer:()=>{},store,effect:wiring,completion_order:[...WORKER_IDS]});
 const effectEvents=()=>events.filter(e=>['audit-approval','marker','submit','store-effect','audit-effect','crash'].includes(e));
 const cleanup=()=>rmSync(root,{recursive:true,force:true});
 return {run,store:realStore,ledger:realLedger,audit:realAudit,counts,drains:()=>drains,peak:()=>peak,crashes:()=>crashes,effectEvents,cleanup};
}
test('no_submission_without_granted_approval',async()=>{
 const p=probe('rejected');
 const summary=await p.run();
 expect(summary.rejected).toBe(true);expect(summary.effect).toBeNull();
 expect(p.ledger.records()).toEqual([]);
 expect(p.audit.records()).toEqual([{kind:'approval',operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:DIGEST,decision:'rejected',approver:'approver-primary'}]);
 expect(p.effectEvents()).toEqual(['audit-approval']);
 expect(p.store.state().submit_marker).toBeNull();expect(p.store.state().effect).toBeNull();
 p.cleanup();
});
test('submit_marker_precedes_ledger_submit_and_outcome_recorded_after',async()=>{
 const p=probe('granted');
 const summary=await p.run();
 expect(summary.rejected).toBe(false);expect(summary.effect).toEqual(CONFIRMED);
 expect(p.effectEvents()).toEqual(['audit-approval','marker','submit','store-effect','audit-effect']);
 expect(p.store.state().effect).toEqual(CONFIRMED);
 p.cleanup();
 const crashed=probe('granted',{controls:{crash_in_submit_window:true}});
 await expect(crashed.run()).rejects.toBeInstanceOf(CrashSignal);
 expect(crashed.crashes()).toBe(1);expect(crashed.drains()).toBe(0);
 expect(crashed.effectEvents()).toEqual(['audit-approval','marker','submit','crash']);
 expect(crashed.store.state().submit_marker).toEqual({key:KEY,payload_digest:DIGEST});
 expect(crashed.store.state().effect).toBeNull();
 expect(crashed.ledger.records()).toHaveLength(1);
 crashed.cleanup();
});
test('reads_bounded_and_effect_submitted_once',async()=>{
 const p=probe('granted');
 const summary=await p.run();
 expect([...p.counts.values()]).toEqual([1,1,1]);
 expect(p.peak()).toBeLessThanOrEqual(2);expect(summary.peakConcurrency).toBe(2);
 expect(summary.reads.map(r=>r.status)).toEqual(['SUCCEEDED','SUCCEEDED','SUCCEEDED']);
 expect(summary.reads.map(r=>r.worker_id)).toEqual([...WORKER_IDS]);
 expect(p.ledger.records()).toEqual([{key:KEY,payload_digest:DIGEST,effect:{status:'EFFECT_COMPLETED',outcome:CONFIRMED.outcome}}]);
 expect(p.audit.records().map(r=>r.kind)).toEqual(['approval','effect']);
 expect(p.audit.records()[1]).toEqual({kind:'effect',operation:'cancel-and-refund',order_id:'ORD-1001',idempotency_key:KEY,effect_status:'EFFECT_COMPLETED',duplicate:false});
 p.cleanup();
});
test('declared_read_failures_stop_before_approval',async()=>{
 for(const fixture of ['partial-failure','all-failed']){
  const p=probe('granted',{fixture});
  const summary=await p.run();
  expect(summary.rejected).toBe(false);expect(summary.effect).toBeNull();
  expect(summary.reads.some(r=>r.status==='FAILED')).toBe(true);
  expect(p.ledger.records()).toEqual([]);expect(p.audit.records()).toEqual([]);
  expect(p.effectEvents()).toEqual([]);
  p.cleanup();
 }
});
test('store_is_optional_plain_m4_reads_when_absent',async()=>{
 const root=mkdtempSync(join(tmpdir(),'br-m5-exec-'));
 const spec:CaseSpec={case_id:'probe-nostore',execution_mode:'parallel',worker_fixture:'fixtures/workers/order-brief/complete.yaml',completion_order:[...WORKER_IDS],approval:{decision:'granted',approver:'approver-primary'}};
 const provider=new ScriptedWorkers(spec,'ORD-1001');
 const ledger=new EffectLedger(root);
 const wiring:EffectWiring={ledger,approvalGate:new ApprovalGate({decision:'granted',approver:'approver-primary'})};
 const summary=await executeWorkers({mode:'parallel',input:{order_id:'ORD-1001'},directory:createWorkerDirectory(provider),control:provider,observer:()=>{},effect:wiring,completion_order:[...WORKER_IDS]});
 expect(summary.reads.map(r=>r.status)).toEqual(['SUCCEEDED','SUCCEEDED','SUCCEEDED']);
 expect(summary.effect).toBeNull();expect(summary.rejected).toBe(false);
 expect(ledger.records()).toEqual([]);
 rmSync(root,{recursive:true,force:true});
});
test('crash_before_submit_fires_before_the_marker',async()=>{
 const p=probe('granted',{controls:{crash_before_submit:true}});
 await expect(p.run()).rejects.toBeInstanceOf(CrashSignal);
 expect(p.crashes()).toBe(1);expect(p.drains()).toBe(0);
 expect(p.effectEvents()).toEqual(['audit-approval','crash']);
 expect(p.ledger.records()).toEqual([]);
 expect(p.store.state().submit_marker).toBeNull();
 p.cleanup();
});




