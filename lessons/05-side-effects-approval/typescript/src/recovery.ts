import {effectDigest,effectKey} from './idempotency.js';
import {StateStore,loadRunState} from './state-store.js';
import type {EffectConfirmation,EffectPayload,RecoveryControls,RunStateDocument,StateBinding,WorkerOutcome} from './types.js';
import type {AuditSink,EffectSink} from './types.js';
export class RecoveryError extends Error {}
export interface RecoveryOptions {stateRoot:string;binding:StateBinding;ledger:EffectSink;audit?:AuditSink|undefined;controls?:RecoveryControls|undefined}
export interface RecoveryResult {status:'SUCCEEDED'|'UNKNOWN';reconciled:boolean;effect:EffectConfirmation|null;idempotency_key:string|null;reads:WorkerOutcome[]}
function effectPayload(orderId:string):EffectPayload {
 return {operation:'cancel-and-refund',order_id:orderId,refund_amount_cents:4200,currency:'EUR'};
}
function recordedReads(document:RunStateDocument):WorkerOutcome[] {
 return document.steps.filter(step=>step.status==='SUCCEEDED'||step.status==='FAILED')
  .map(step=>({worker_id:step.worker_id,status:step.status,output:structuredClone(step.output),failure_code:step.failure_code}) as WorkerOutcome);
}
export function resumeRun(options:RecoveryOptions):RecoveryResult {
 const loaded=loadRunState(options.stateRoot,options.binding);
 const document=loaded.document;
 if(document.status!=='RUNNING')throw new RecoveryError(`Run state is not resumable (run_id=${document.run_id} status=${document.status})`);
 const store=StateStore.resume(document,loaded.restored_from);
 const reads=recordedReads(document);
 const payload=effectPayload(options.binding.requested_order_id);
 const key=effectKey(payload);
 if(document.effect!==null){
  store.markTerminal('SUCCEEDED');
  return {status:'SUCCEEDED',reconciled:false,effect:document.effect,idempotency_key:document.effect.key,reads};
 }
 const marker=document.submit_marker;
 if(marker===null)throw new RecoveryError(`Run state has no effect decision to resolve (run_id=${document.run_id})`);
 if(marker.key!==key||marker.payload_digest!==effectDigest(payload))throw new RecoveryError(`Effect binding mismatch (run_id=${document.run_id})`);
 if(options.controls?.sink_unavailable===true){
  store.markTerminal('UNKNOWN');
  return {status:'UNKNOWN',reconciled:false,effect:null,idempotency_key:key,reads};
 }
 const found=options.ledger.lookup(key);
 if(found!==null){
  const adopted:EffectConfirmation={key,payload_digest:marker.payload_digest,status:found.status,outcome:found.outcome,duplicate:false};
  store.recordEffectOutcome(adopted);
  options.audit?.append({kind:'effect',operation:'cancel-and-refund',order_id:options.binding.requested_order_id,idempotency_key:key,effect_status:found.status,duplicate:false});
  store.markTerminal('SUCCEEDED');
  return {status:'SUCCEEDED',reconciled:true,effect:adopted,idempotency_key:key,reads};
 }
 const submitted=options.ledger.submit(key,marker.payload_digest,payload);
 const effect:EffectConfirmation={key,payload_digest:marker.payload_digest,status:submitted.status,outcome:submitted.outcome,duplicate:submitted.duplicate};
 store.recordEffectOutcome(effect);
 options.audit?.append({kind:'effect',operation:'cancel-and-refund',order_id:options.binding.requested_order_id,idempotency_key:key,effect_status:submitted.status,duplicate:submitted.duplicate});
 store.markTerminal('SUCCEEDED');
 return {status:'SUCCEEDED',reconciled:false,effect,idempotency_key:key,reads};
}

