import {expect,test} from 'vitest';
import {existsSync,mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {WORKER_IDS,StateLoadError,type StateBinding,type WorkerOutcome,type WorkerOutput} from '../src/types.js';
import {StateStore,loadRunState} from '../src/state-store.js';
const binding:StateBinding={case_id:'approval-granted-effect-once',execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2};
const succeeded=(id:typeof WORKER_IDS[number]):WorkerOutcome=>({
 worker_id:id,status:'SUCCEEDED',output:({['order-details']:{order_id:'ORD-1001',order_status:'SHIPPED'},['payment-status']:{order_id:'ORD-1001',payment_status:'PAID'},['delivery-status']:{order_id:'ORD-1001',delivery_status:'DELAYED'}} as Record<string,WorkerOutput>)[id]!,failure_code:null});
const failed=(id:typeof WORKER_IDS[number]):WorkerOutcome=>({worker_id:id,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'});
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m5-state-'));}
test('create_writes_initial_loadable_state_and_checkpoints_terminals',()=>{
 const root=freshRoot();const store=StateStore.create(root,binding,[...WORKER_IDS]);
 const doc=store.state();
 expect(doc.scenario_id).toBe('order-closure');
 expect(doc.status).toBe('RUNNING');expect(doc.sequence_cursor).toBe(0);expect(doc.digest).toMatch(/^[0-9a-f]{64}$/);
 expect(doc.steps.map(s=>s.status)).toEqual(['PENDING','PENDING','PENDING']);
 const loaded=loadRunState(root,binding);
 expect(loaded.document.run_id).toBe(doc.run_id);expect(loaded.restored_from).toBe(store.statePath());
 store.markRunning('order-details');expect(store.state().steps[0]!.status).toBe('RUNNING');
 store.recordStepTerminal('order-details',succeeded('order-details'));
 expect(store.state().sequence_cursor).toBe(1);
 const snapshot=readFileSync(store.snapshotPath(1),'utf8');
 expect(JSON.parse(snapshot).steps[0].output).toEqual({order_id:'ORD-1001',order_status:'SHIPPED'});
 store.recordStepTerminal('payment-status',succeeded('payment-status'));
 expect(readFileSync(store.snapshotPath(1),'utf8')).toBe(snapshot);
 store.recordStepTerminal('delivery-status',failed('delivery-status'));
 expect(store.state().sequence_cursor).toBe(3);expect(existsSync(store.snapshotPath(3))).toBe(true);
 rmSync(root,{recursive:true,force:true});
});
test('mark_cancelled_from_and_m5_terminal_failure_codes',()=>{
 const root=freshRoot();const store=StateStore.create(root,binding,[...WORKER_IDS]);
 store.recordStepTerminal('order-details',succeeded('order-details'));
 store.recordStepTerminal('payment-status',succeeded('payment-status'));
 store.markCancelledFrom('delivery-status');
 expect(store.state().steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','CANCELLED']);
 store.markTerminal('CANCELLED');
 expect(store.state().status).toBe('CANCELLED');
 expect(loadRunState(root,binding).document.status).toBe('CANCELLED');
 store.markTerminal('FAILED','APPROVAL_REJECTED');
 expect(store.state().status).toBe('FAILED');
 expect(()=>store.markTerminal('FAILED','OTHER' as 'ALL_WORKERS_FAILED')).toThrow();
 expect(()=>store.markTerminal('FAILED')).toThrow();
 store.markTerminal('UNKNOWN');
 expect(store.state().status).toBe('UNKNOWN');
 expect(loadRunState(root,binding).document.status).toBe('UNKNOWN');
 rmSync(root,{recursive:true,force:true});
});
test('reject_tampered_state_document_fails_closed_with_fixed_reasons',()=>{
 const root=freshRoot();const store=StateStore.create(root,binding,[...WORKER_IDS]);
 store.recordStepTerminal('order-details',succeeded('order-details'));
 store.recordStepTerminal('payment-status',succeeded('payment-status'));
 const path=store.statePath();
 const good=readFileSync(path,'utf8');
 const mutate=(apply:(doc:any)=>void):void=>{const doc=JSON.parse(good);apply(doc);writeFileSync(path,JSON.stringify(doc));};
 const fails=(binding2:StateBinding,reason:string):string=>{try{loadRunState(root,binding2);expect.unreachable();}catch(error){const message=(error as Error).message;expect(message).toContain(reason);return message;}return '';};
 mutate(doc=>{doc.steps[1].output.payment_status='UNPAID';});
 expect(fails(binding,'DIGEST_MISMATCH')).not.toContain('UNPAID');
 mutate(doc=>{doc.state_schema_version='2.0';});
 fails(binding,'UNKNOWN_VERSION');
 mutate(doc=>{delete doc.sequence_cursor;});
 fails(binding,'SCHEMA_INVALID');
 mutate(doc=>{doc.digest='a'.repeat(64);});
 fails(binding,'DIGEST_MISMATCH');
 writeFileSync(path,good);
 fails({...binding,case_id:'other-case'},'BINDING_MISMATCH');
 writeFileSync(path,'{"state_schema_version":"1.0","run_');
 fails(binding,'TRUNCATED');
 writeFileSync(path,good);
});
test('atomic_write_leaves_previous_state_loadable',()=>{
 const root=freshRoot();const store=StateStore.create(root,binding,[...WORKER_IDS]);
 store.recordStepTerminal('order-details',succeeded('order-details'));
 const path=store.statePath();
 writeFileSync(path+'.tmp','{"state_schema_version":"1.0","run_');
 expect(JSON.parse(readFileSync(path,'utf8')).steps[0].status).toBe('SUCCEEDED');
 const loaded=loadRunState(root,binding);
 expect(loaded.document.sequence_cursor).toBe(1);
 store.markRunning('payment-status');
 expect(existsSync(path+'.tmp')).toBe(false);
 expect(loadRunState(root,binding).document.steps[1]!.status).toBe('RUNNING');
 rmSync(root,{recursive:true,force:true});
});
test('missing_checkpoint_snapshot_fails_closed',()=>{
 const root=freshRoot();const store=StateStore.create(root,binding,[...WORKER_IDS]);
 store.recordStepTerminal('order-details',succeeded('order-details'));
 rmSync(store.snapshotPath(1));
 try{loadRunState(root,binding);expect.unreachable();}catch(error){expect((error as Error).message).toContain('MISSING_SNAPSHOT');}
 rmSync(root,{recursive:true,force:true});
});
test('flat_layout_loads_and_ambiguous_discovery_fails',()=>{
 const root=freshRoot();const store=StateStore.create(root,binding,[...WORKER_IDS]);
 store.recordStepTerminal('order-details',succeeded('order-details'));
 const flat=join(root,'state.json');const nested=store.statePath();
 writeFileSync(flat,readFileSync(nested,'utf8'));
 const loaded=loadRunState(root,binding);
 expect(loaded.restored_from).toBe(flat);expect(loaded.document.run_id).toBe(store.state().run_id);
 rmSync(flat);
 expect(loadRunState(root,binding).restored_from).toBe(nested);
 rmSync(root,{recursive:true,force:true});
 const empty=freshRoot();
 try{loadRunState(empty,binding);expect.unreachable();}catch(error){expect(error).not.toBeInstanceOf(StateLoadError);expect((error as Error).message).toContain('exactly one');}
 rmSync(empty,{recursive:true,force:true});
 const crowded=freshRoot();StateStore.create(crowded,binding,[...WORKER_IDS]);StateStore.create(crowded,binding,[...WORKER_IDS]);
 try{loadRunState(crowded,binding);expect.unreachable();}catch(error){expect(error).not.toBeInstanceOf(StateLoadError);expect((error as Error).message).toContain('exactly one');}
 rmSync(crowded,{recursive:true,force:true});
});




