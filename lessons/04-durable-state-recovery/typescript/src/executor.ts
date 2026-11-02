import {WORKER_IDS,WorkerExecutionError,type ExecutorOptions,type ExecutionSummary,type StateStore,type WorkerId,type WorkerOutcome} from './types.js';
import {validateWorkerOutput} from './schemas.js';
export class CrashSignal extends Error {}
function crashBoundaryReady(store:StateStore,crashAfter:WorkerId):boolean {
 const document=store.state(),step=document.steps[WORKER_IDS.indexOf(crashAfter)]!;
 const recorded=document.steps.filter(entry=>entry.status==='SUCCEEDED'||entry.status==='FAILED').length;
 return document.status==='RUNNING'&&(step.status==='SUCCEEDED'||step.status==='FAILED')&&document.sequence_cursor===recorded;
}
export async function executeWorkers(options:ExecutorOptions):Promise<ExecutionSummary>{
 const {mode,input,directory,control,observer}=options;
 const store=options.store,controls=options.controls,onCrash=options.on_crash;
 if(!['sequential','parallel'].includes(mode)||typeof input.order_id!=='string'||!/^ORD-[0-9]{4}$/.test(input.order_id)||Object.keys(input).join('|')!=='order_id')throw new Error('Invalid execution input');
 const queue=options.queue??WORKER_IDS,expected=[...WORKER_IDS].filter(id=>queue.includes(id));
 if(new Set(queue).size!==queue.length||queue.length!==expected.length||queue.some((id,index)=>id!==expected[index]))throw new Error('Invalid execution queue');
 const crashAfter=controls?.crash_after,cancelBefore=controls?.cancel_before;
 if(crashAfter!==undefined&&cancelBefore!==undefined)throw new Error('At most one control is allowed');
 if(crashAfter!==undefined&&(store===undefined||onCrash===undefined))throw new Error('Crash control requires store and on_crash');
 const crashPos=crashAfter===undefined?undefined:WORKER_IDS.indexOf(crashAfter)+1;
 const limit=mode==='sequential'?1:2,pending=[...queue],outcomes:WorkerOutcome[]=[];
 type Settled={id:WorkerId;outcome:WorkerOutcome}|{id:WorkerId;error:unknown};
 const active=new Map<WorkerId,Promise<Settled>>();let peak=0,fatalSeen=false,fatal:unknown,cancelFired=false;
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
   while(!fatalSeen&&!cancelFired&&pending.length&&active.size<limit){
    const next=pending[0]!;
    if(cancelBefore!==undefined&&next===cancelBefore){cancelFired=true;break;}
    if(crashPos!==undefined&&WORKER_IDS.indexOf(next)>=crashPos)break;
    pending.shift();store?.markRunning(next);active.set(next,invoke(next));peak=Math.max(peak,active.size);
   }
   if(fatalSeen)throw fatal;
   if(cancelFired&&active.size===0)break;
   const settled=await Promise.race(active.values());
   if(fatalSeen||'error' in settled)throw fatal;
   active.delete(settled.id);
   store?.recordStepTerminal(settled.id,settled.outcome);
   if(crashAfter!==undefined&&store!==undefined&&onCrash!==undefined&&active.size===0&&crashBoundaryReady(store,crashAfter))onCrash();
   outcomes.push(settled.outcome);observer({kind:'terminal',outcome:settled.outcome});control.acknowledgeOutcome(settled.id);
  }
  const summary:ExecutionSummary={outcomes,peakConcurrency:peak};
  if(cancelFired&&cancelBefore!==undefined)summary.cancelled_before=cancelBefore;
  return summary;
 }catch(error){if(error instanceof CrashSignal)throw error;control.beginDrain();await Promise.all(active.values());throw error;}
}
