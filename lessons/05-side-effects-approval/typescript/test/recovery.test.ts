import {expect,test} from 'vitest';
import {mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {CrashSignal,executeWorkers} from '../src/executor.js';
import {RecoveryError,resumeRun} from '../src/recovery.js';
import {StateStore,loadRunState} from '../src/state-store.js';
import {EffectLedger} from '../src/effect-ledger.js';
import {AuditWriter} from '../src/audit.js';
import {ApprovalGate} from '../src/approval.js';
import {effectDigest,effectKey} from '../src/idempotency.js';
import {canonicalJson,canonicalStateBody,stateDigest} from '../src/schemas.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
import {createWorkerDirectory} from '../src/workers.js';
import {WORKER_IDS,type AuditSink,type CaseSpec,type EffectConfirmation,type EffectPayload,type EffectSink,type RecoveryControls,type StateBinding,type WorkerProvider} from '../src/types.js';
const PAYLOAD:EffectPayload={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'};
const KEY=effectKey(PAYLOAD),DIGEST=effectDigest(PAYLOAD);
const OUTCOME={refund_id:'RFL-1001',refunded_at:'2026-11-02T00:00:00Z'};
const ADOPTED:EffectConfirmation={key:KEY,payload_digest:DIGEST,status:'EFFECT_COMPLETED',outcome:OUTCOME,duplicate:false};
const BINDING:StateBinding={case_id:'seed',execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2};
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m5-rec-'));}
async function seedRun(root:string,decision:'granted'|'rejected',controls?:RecoveryControls):Promise<void> {
 const spec:CaseSpec={case_id:'seed',execution_mode:'parallel',worker_fixture:'fixtures/workers/order-brief/complete.yaml',completion_order:[...WORKER_IDS],approval:{decision:'granted',approver:'approver-primary'}};
 const provider=new ScriptedWorkers(spec,'ORD-1001');
 const store=new StateStore(root,BINDING,[...WORKER_IDS]);
 const wiring={ledger:new EffectLedger(root),approvalGate:new ApprovalGate({decision,approver:'approver-primary'}),audit:new AuditWriter(root),controls,
  on_crash:()=>{throw new CrashSignal('crash');}};
 await executeWorkers({mode:'parallel',input:{order_id:'ORD-1001'},directory:createWorkerDirectory(provider),control:provider,observer:()=>{},store,effect:wiring,completion_order:[...WORKER_IDS]}).then(()=>undefined,error=>{if(!(error instanceof CrashSignal))throw error;});
}
interface Spy {reads:number;ledger:EffectLedger;audit:AuditWriter;ledgerSpy:EffectSink;auditSpy:AuditSink&{records:()=>unknown};lookups:number;submits:number}
function spies(root:string):Spy {
 const ledger=new EffectLedger(root);const audit=new AuditWriter(root);
 const spy:Spy={reads:0,lookups:0,submits:0,ledger,audit,ledgerSpy:{submit:(k,d,p)=>{spy.submits++;return ledger.submit(k,d,p);},lookup:k=>{spy.lookups++;return ledger.lookup(k);}},
  auditSpy:{append:r=>audit.append(r),records:()=>{spy.reads++;return audit.records();}}};
 return spy;
}
test('resume_proves_landed_effect_by_key_lookup',async()=>{
 const root=freshRoot();
 await seedRun(root,'granted',{crash_in_submit_window:true});
 const spy=spies(root);
 const result=resumeRun({stateRoot:root,binding:BINDING,ledger:spy.ledgerSpy,audit:spy.auditSpy});
 expect(result.status).toBe('SUCCEEDED');expect(result.reconciled).toBe(true);
 expect(result.idempotency_key).toBe(KEY);expect(result.effect).toEqual(ADOPTED);
 expect(result.reads.map(r=>r.status)).toEqual(['SUCCEEDED','SUCCEEDED','SUCCEEDED']);
 const {document}=loadRunState(root,BINDING);
 expect(document.status).toBe('SUCCEEDED');expect(document.effect).toEqual(ADOPTED);
 expect(document.submit_marker).toEqual({key:KEY,payload_digest:DIGEST});
 expect(spy.ledger.records()).toEqual([{key:KEY,payload_digest:DIGEST,effect:{status:'EFFECT_COMPLETED',outcome:OUTCOME}}]);
 expect(spy.submits).toBe(0);
 expect(spy.audit.records().map(r=>r.kind)).toEqual(['approval','effect']);
 expect(spy.reads).toBe(0);
 rmSync(root,{recursive:true,force:true});
});
test('resume_resubmits_absent_effect_under_same_key',async()=>{
 const root=freshRoot();
 await seedRun(root,'granted',{crash_in_submit_window:true});
 rmSync(join(root,'effect-ledger.json'));
 const spy=spies(root);
 const result=resumeRun({stateRoot:root,binding:BINDING,ledger:spy.ledgerSpy,audit:spy.auditSpy});
 expect(result.status).toBe('SUCCEEDED');expect(result.reconciled).toBe(false);
 expect(result.effect).toEqual({...ADOPTED,duplicate:false});
 expect(spy.ledger.records()).toEqual([{key:KEY,payload_digest:DIGEST,effect:{status:'EFFECT_COMPLETED',outcome:OUTCOME}}]);
 expect(spy.submits).toBe(1);expect(spy.lookups).toBe(1);
 const {document}=loadRunState(root,BINDING);
 expect(document.status).toBe('SUCCEEDED');expect(document.effect).toEqual(result.effect);
 expect(spy.audit.records().map(r=>r.kind)).toEqual(['approval','effect']);
 rmSync(root,{recursive:true,force:true});
});
test('unprovable_effect_stays_unknown',async()=>{
 const root=freshRoot();
 await seedRun(root,'granted',{crash_in_submit_window:true});
 const spy=spies(root);
 const result=resumeRun({stateRoot:root,binding:BINDING,ledger:spy.ledgerSpy,audit:spy.auditSpy,controls:{sink_unavailable:true}});
 expect(result.status).toBe('UNKNOWN');expect(result.reconciled).toBe(false);
 expect(result.effect).toBeNull();expect(result.idempotency_key).toBe(KEY);
 expect(spy.lookups).toBe(0);expect(spy.submits).toBe(0);
 const {document}=loadRunState(root,BINDING);
 expect(document.status).toBe('UNKNOWN');expect(document.effect).toBeNull();
 expect(document.submit_marker).toEqual({key:KEY,payload_digest:DIGEST});
 expect(spy.ledger.records()).toHaveLength(1);
 expect(spy.audit.records()).toHaveLength(1);
 expect(spy.reads).toBe(0);
 rmSync(root,{recursive:true,force:true});
});
test('duplicate_key_adopts_recorded_outcome',async()=>{
 const root=freshRoot();
 await seedRun(root,'granted');
 const ledger=new EffectLedger(root);
 expect(ledger.records()).toHaveLength(1);
 const spec:CaseSpec={case_id:'second',execution_mode:'parallel',worker_fixture:'fixtures/workers/order-brief/complete.yaml',completion_order:[...WORKER_IDS],approval:{decision:'granted',approver:'approver-primary'}};
 const provider=new ScriptedWorkers(spec,'ORD-1001');
 const store=new StateStore(root,BINDING,[...WORKER_IDS]);
 const summary=await executeWorkers({mode:'parallel',input:{order_id:'ORD-1001'},directory:createWorkerDirectory(provider),control:provider,observer:()=>{},store,
  effect:{ledger,approvalGate:new ApprovalGate({decision:'granted',approver:'approver-primary'}),audit:new AuditWriter(root)},completion_order:[...WORKER_IDS]});
 expect(summary.effect).toEqual({...ADOPTED,duplicate:true});
 expect(ledger.records()).toHaveLength(1);
 expect(store.state().effect).toEqual({...ADOPTED,duplicate:true});
 expect(store.state().submit_marker).toEqual({key:KEY,payload_digest:DIGEST});
 rmSync(root,{recursive:true,force:true});
});
test('terminal_states_not_resumable',async()=>{
 for(const status of ['SUCCEEDED','FAILED','CANCELLED','UNKNOWN'] as const){
  const root=freshRoot();
  await seedRun(root,'granted');
  const store=StateStore.resume(loadRunState(root,BINDING).document,loadRunState(root,BINDING).restored_from);
  if(status==='FAILED')store.markTerminal('FAILED','APPROVAL_REJECTED');else store.markTerminal(status);
  const spy=spies(root);
  try{resumeRun({stateRoot:root,binding:BINDING,ledger:spy.ledgerSpy,audit:spy.auditSpy});expect.unreachable();}
  catch(error){expect(error).toBeInstanceOf(RecoveryError);expect((error as Error).message).toContain('not resumable');}
  expect(spy.ledger.records()).toHaveLength(1);expect(spy.submits).toBe(0);
  expect(spy.audit.records()).toHaveLength(2);expect(spy.reads).toBe(0);
  rmSync(root,{recursive:true,force:true});
 }
});
test('binding_mismatch_rejected',async()=>{
 const root=freshRoot();
 await seedRun(root,'granted',{crash_in_submit_window:true});
 const {restored_from}=loadRunState(root,BINDING);
 const doc=JSON.parse(readFileSync(restored_from,'utf8'));
 doc.submit_marker={key:KEY,payload_digest:'d'.repeat(64)};
 doc.digest=stateDigest(canonicalStateBody(doc));
 writeFileSync(restored_from,canonicalJson(doc),'utf8');
 const spy=spies(root);
 try{resumeRun({stateRoot:root,binding:BINDING,ledger:spy.ledgerSpy,audit:spy.auditSpy});expect.unreachable();}
 catch(error){expect(error).toBeInstanceOf(RecoveryError);expect((error as Error).message).toContain('Effect binding mismatch');}
 expect(spy.ledger.records()).toHaveLength(1);expect(spy.submits).toBe(0);expect(spy.lookups).toBe(0);
 expect(spy.audit.records()).toHaveLength(1);expect(spy.reads).toBe(0);
 rmSync(root,{recursive:true,force:true});
});
test('runtime_never_reads_audit',async()=>{
 const root=freshRoot();
 await seedRun(root,'granted',{crash_in_submit_window:true});
 const spy=spies(root);
 resumeRun({stateRoot:root,binding:BINDING,ledger:spy.ledgerSpy,audit:spy.auditSpy});
 expect(spy.reads).toBe(0);
 rmSync(root,{recursive:true,force:true});
});




