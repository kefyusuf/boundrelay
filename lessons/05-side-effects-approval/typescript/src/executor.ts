import {WORKER_IDS,WorkerExecutionError,type EffectConfirmation,type EffectPayload,type ExecutorOptions,type ExecutionSummary,type WorkerId,type WorkerOutcome} from './types.js';
import {validateWorkerOutput} from './schemas.js';
import {effectDigest,effectKey} from './idempotency.js';
import {requireApproval} from './approval.js';
export class CrashSignal extends Error {}
function effectPayload(orderId:string):EffectPayload {
 return {operation:'cancel-and-refund',order_id:orderId,refund_amount_cents:4200,currency:'EUR'};
}
export async function executeWorkers(options:ExecutorOptions):Promise<ExecutionSummary>{
 const {mode,input,directory,control,observer}=options;
 const store=options.store,wiring=options.effect;
 if(!['sequential','parallel'].includes(mode)||typeof input.order_id!=='string'||!/^ORD-[0-9]{4}$/.test(input.order_id)||Object.keys(input).join('|')!=='order_id')throw new Error('Invalid execution input');
 const queue=options.queue??WORKER_IDS,expected=[...WORKER_IDS].filter(id=>queue.includes(id));
 if(new Set(queue).size!==queue.length||queue.length!==expected.length||queue.some((id,index)=>id!==expected[index]))throw new Error('Invalid execution queue');
 const limit=mode==='sequential'?1:2,pending=[...queue],reads:WorkerOutcome[]=[];
 type Settled={id:WorkerId;outcome:WorkerOutcome}|{id:WorkerId;error:unknown};
 const active=new Map<WorkerId,Promise<Settled>>();let peak=0,fatalSeen=false,fatal:unknown;
 const invoke=async(id:WorkerId):Promise<Settled>=>{
  try{
   const worker=directory.resolve(id);if(worker===undefined||worker.id!==id)throw new Error('Unknown worker');
   const isolated=Object.freeze({order_id:input.order_id});observer({kind:'started',worker_id:id,input:isolated});
   let outcome:WorkerOutcome;
   try{
    const validation=validateWorkerOutput(id,await worker.handle(isolated),input.order_id);
    outcome=validation.valid?{worker_id:id,status:'SUCCEEDED',output:validation.value,failure_code:null}:{worker_id:id,status:'FAILED',output:null,failure_code:'INVALID_WORKER_OUTPUT'};
   }catch(error){if(!(error instanceof WorkerExecutionError))throw error;outcome={worker_id:id,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'};}
   return {id,outcome};
  }catch(error){if(!fatalSeen){fatalSeen=true;fatal=error;}return {id,error};}
 };
 try{
  while(pending.length||active.size){
   while(!fatalSeen&&pending.length&&active.size<limit){
    const next=pending.shift()!;
    store?.markRunning(next);active.set(next,invoke(next));peak=Math.max(peak,active.size);
   }
   if(fatalSeen)throw fatal;
   const settled=await Promise.race(active.values());
   if(fatalSeen||'error' in settled)throw fatal;
   active.delete(settled.id);
   store?.recordStepTerminal(settled.id,settled.outcome);
   reads.push(settled.outcome);observer({kind:'terminal',outcome:settled.outcome});control.acknowledgeOutcome(settled.id);
  }
  if(wiring===undefined||store===undefined||!reads.every(outcome=>outcome.status==='SUCCEEDED'))return {reads,effect:null,rejected:false,peakConcurrency:peak};
  const payload=effectPayload(input.order_id),key=effectKey(payload),digest=effectDigest(payload);
  const events=wiring.events;
  events?.emit('approval.requested',{operation:'cancel-and-refund',order_id:input.order_id,payload_digest:digest});
  const decisionRecord=wiring.approvalGate.decide(payload);
  events?.emit(decisionRecord.decision==='granted'?'approval.granted':'approval.rejected',{operation:'cancel-and-refund',order_id:input.order_id,payload_digest:digest});
  wiring.audit?.append({kind:'approval',...decisionRecord.record});
  if(decisionRecord.decision!=='granted')return {reads,effect:null,rejected:true,peakConcurrency:peak};
  requireApproval(decisionRecord.record,payload);
  if(wiring.controls?.crash_before_submit===true){
   if(wiring.on_crash===undefined)throw new Error('Crash control requires on_crash');
   wiring.on_crash();
  }
  store.markSubmitted(key,digest);
  events?.emit('tool.requested',{key,payload_digest:digest,side_effect_class:'external'});
  let submitted;
  try{submitted=wiring.ledger.submit(key,digest,payload);}
  catch(error){events?.emit('tool.failed',{key});throw error;}
  if(wiring.controls?.crash_in_submit_window===true){
   if(wiring.on_crash===undefined)throw new Error('Crash control requires on_crash');
   wiring.on_crash();
  }
  const effect:EffectConfirmation={key,payload_digest:digest,status:submitted.status,outcome:submitted.outcome,duplicate:submitted.duplicate};
  events?.emit('tool.completed',{key,status:submitted.status,duplicate:submitted.duplicate});
  store.recordEffectOutcome(effect);
  wiring.audit?.append({kind:'effect',operation:'cancel-and-refund',order_id:input.order_id,idempotency_key:key,effect_status:submitted.status,duplicate:submitted.duplicate});
  return {reads,effect,rejected:false,peakConcurrency:peak};
 }catch(error){if(error instanceof CrashSignal)throw error;control.beginDrain();await Promise.all(active.values());throw error;}
}


