import {WORKER_IDS,WorkerExecutionError,type ExecutorOptions,type ExecutionSummary,type WorkerId,type WorkerOutcome} from './types.js';
import {validateWorkerOutput} from './schemas.js';
export async function executeWorkers(options:ExecutorOptions):Promise<ExecutionSummary>{
 const {mode,input,directory,control,observer}=options;
 if(!['sequential','parallel'].includes(mode)||typeof input.order_id!=='string'||!/^ORD-[0-9]{4}$/.test(input.order_id)||Object.keys(input).join('|')!=='order_id')throw new Error('Invalid execution input');
 const limit=mode==='sequential'?1:2,pending=[...WORKER_IDS],outcomes:WorkerOutcome[]=[];
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
   observer({kind:'terminal',outcome});return {id,outcome};
  }catch(error){if(!fatalSeen){fatalSeen=true;fatal=error;}return {id,error};}
 };
 try{
  while(pending.length||active.size){
   while(!fatalSeen&&pending.length&&active.size<limit){const id=pending.shift()!;active.set(id,invoke(id));peak=Math.max(peak,active.size);}
   if(fatalSeen)throw fatal;
   const settled=await Promise.race(active.values());
   if(fatalSeen||'error' in settled)throw fatal;
   outcomes.push(settled.outcome);control.acknowledgeOutcome(settled.id);active.delete(settled.id);
  }
  return {outcomes,peakConcurrency:peak};
 }catch(error){control.beginDrain();await Promise.all(active.values());throw error;}
}
