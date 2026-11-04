import {loadScenario} from './scenario.js';import {buildAttribution,workerRecords} from './attribution.js';import {ScriptedWorkers} from './scripted-workers.js';import {createWorkerDirectory} from './workers.js';import {executeWorkers} from './executor.js';import {canonicalizeOutcomes} from './collector.js';import {synthesizeBrief} from './synthesizer.js';import {TraceSink} from './trace.js';import {validateRunResult} from './schemas.js';import {StateStore,loadRunState,loadRunStateDocument} from './state-store.js';import {resumeRun,replayFrom,recordedOutcomes,derivePending,type RunOptions,type RecoverySink} from './recovery.js';
export type {RunOptions} from './recovery.js';
import {WORKER_IDS} from './types.js';
import type {Brief,CaseSpec,Scenario,StateBinding,WorkerControl,WorkerDirectory,WorkerObserver,WorkerOutcome} from './types.js';
import type {RunResult} from './types.js';
type EventSink=RecoverySink&{flush:()=>void};
function checkpointSaved(binding:StateBinding,store:StateStore,workerId:string):Record<string,unknown> {
 const document=store.state();
 return {case_id:binding.case_id,execution_mode:binding.execution_mode,requested_order_id:binding.requested_order_id,concurrency_limit:binding.concurrency_limit,step_name:workerId,state_status:document.status,sequence_cursor:document.sequence_cursor};
}
function stepObserver(sink:EventSink):WorkerObserver {
 return event=>{
  if(event.kind==='started')sink.emit('step.started',{step_name:'worker.'+event.worker_id,worker_id:event.worker_id,order_id:event.input.order_id});
  else sink.emit(event.outcome.status==='SUCCEEDED'?'step.completed':'step.failed',{step_name:'worker.'+event.outcome.worker_id,outcome:event.outcome});
 };
}
function observerFor(sink:EventSink,binding:StateBinding,store:StateStore):WorkerObserver {
 const step=stepObserver(sink);
 return event=>{
  step(event);
  if(event.kind==='terminal')sink.emit('checkpoint.saved',checkpointSaved(binding,store,event.outcome.worker_id));
 };
}
async function freshRun(options:RunOptions,spec:CaseSpec,scenario:Scenario,binding:StateBinding,store:StateStore,sink:EventSink):Promise<RunResult> {
 const tables=scenario.attribution;
 if(tables===null)throw new Error('Scenario is missing attribution tables');
 const attribute=(outcomes:readonly WorkerOutcome[],synthesisInvoked:boolean):RunResult['attribution']=>buildAttribution([...workerRecords(outcomes),...(synthesisInvoked?[['synthesize',1] as const]:[])],tables.price_table,tables.latency_ms);
 const provider=options.directory===undefined?new ScriptedWorkers(spec,scenario.order_id):undefined;
 const execution=await executeWorkers({mode:spec.execution_mode,input:{order_id:scenario.order_id},directory:options.directory??createWorkerDirectory(provider!),control:options.control??provider!,observer:observerFor(sink,binding,store),store,completion_order:[...spec.completion_order],on_crash:options.on_crash??(()=>{sink.flush();process.exit(2);}),...(spec.controls?{controls:spec.controls}:{})});
 if(execution.cancelled_before!==undefined){
  store.markCancelledFrom(execution.cancelled_before);
  sink.emit('run.cancelled',{case_id:binding.case_id,execution_mode:binding.execution_mode,requested_order_id:binding.requested_order_id,concurrency_limit:binding.concurrency_limit,cancelled_before:execution.cancelled_before,code:'CANCELLED_BEFORE_STEP'});
  store.markTerminal('CANCELLED');
  const result=assemble(options,binding,store.state().run_id,execution.peakConcurrency,'CANCELLED',recordedOutcomes(store.state()),false,null,null,attribute(recordedOutcomes(store.state()),false));
  if(!validateRunResult(result))throw new Error('Invalid run result');
  return result;
 }
 const outcomes=canonicalizeOutcomes(execution.outcomes,scenario.order_id),successes=outcomes.filter(o=>o.status==='SUCCEEDED').length;
 if(successes)sink.emit('step.started',{step_name:'synthesize',worker_outcomes:outcomes});
 const brief=successes?(options.synthesizer??synthesizeBrief)(scenario.order_id,outcomes):null;
 if(successes)sink.emit('step.completed',{step_name:'synthesize',brief});
 const status=successes===3?'SUCCEEDED':successes?'PARTIAL':'FAILED',failureCode=successes?null:'ALL_WORKERS_FAILED';
 if(failureCode===null)store.markTerminal(status);else store.markTerminal(status,failureCode);
 const result=assemble(options,binding,store.state().run_id,execution.peakConcurrency,status,outcomes,successes>0,brief,failureCode,attribute(outcomes,successes>0));
 if(!validateRunResult(result))throw new Error('Invalid run result');
 return result;
}
function assemble(options:RunOptions,binding:StateBinding,runId:string,peak:number,status:'SUCCEEDED'|'PARTIAL'|'FAILED'|'CANCELLED',outcomes:readonly WorkerOutcome[],synthesisInvoked:boolean,brief:Brief|null,failureCode:'ALL_WORKERS_FAILED'|null,attribution:RunResult['attribution']):RunResult {
 return {schema_version:'1.0',run_id:runId,scenario_id:'order-brief-recovery',case_id:binding.case_id,execution_mode:binding.execution_mode,concurrency_limit:binding.concurrency_limit,peak_concurrency:Math.max(peak,1),order_id:binding.requested_order_id,status,worker_outcomes:outcomes as RunResult['worker_outcomes'],synthesis_invoked:synthesisInvoked,brief,failure_code:failureCode,trace_path:options.tracePath,resumed:false,restored_cursor:null,restored_worker_ids:[],state_dir:options.stateDir,run_state_status:status,attribution};
}
export async function runCase(options:RunOptions):Promise<RunResult>{
 const scenario=loadScenario(),spec=scenario.cases.find(c=>c.case_id===options.caseId);
 if(spec===undefined||!options.tracePath||!options.stateDir)throw new Error('Unknown case or missing options');
 if((options.directory===undefined)!==(options.control===undefined))throw new Error('Directory and control must be supplied together');
 if(options.resume&&options.replayFrom!==undefined)throw new Error('Resume and replay are mutually exclusive');
 const binding:StateBinding={case_id:spec.case_id,execution_mode:spec.execution_mode,requested_order_id:scenario.order_id,concurrency_limit:spec.execution_mode==='sequential'?1:2};
 const context={scenario_id:'order-brief-recovery',case_id:spec.case_id,execution_mode:spec.execution_mode,order_id:scenario.order_id,concurrency_limit:binding.concurrency_limit,state_dir:options.stateDir};
 const loaded=options.resume?loadRunState(options.stateDir,binding):undefined;
 const replayDocument=options.replayFrom!==undefined?loadRunStateDocument(options.replayFrom,binding):undefined;
 const pending=loaded?derivePending(loaded.document):replayDocument?derivePending(replayDocument):[];
 const store=loaded?undefined:(():StateStore=>{
  const created=options.stateStore??StateStore.create(options.stateDir,binding,[...WORKER_IDS]);
  if(options.stateStore===undefined&&replayDocument!==undefined)for(const outcome of recordedOutcomes(replayDocument))created.recordStepTerminal(outcome.worker_id,outcome);
  return created;})();
 const runId=loaded?loaded.document.run_id:store!.state().run_id;
 const created=new TraceSink(runId,options.tracePath);
 const sink=(options.sink as (RecoverySink&{flush:()=>void})|undefined)??created;
 try{
  sink.emit('run.created',context);sink.emit('run.started',context);
  const resumeSpec:CaseSpec={...spec,execution_mode:pending.length>1?spec.execution_mode:'sequential',completion_order:spec.completion_order.filter(id=>pending.includes(id))};
  const provider=options.directory===undefined?new ScriptedWorkers(resumeSpec,scenario.order_id):undefined;
  const directory=options.directory??createWorkerDirectory(provider!),control=options.control??provider!;
  const result=loaded?await resumeRun((({stateStore:_unused,...rest}:typeof options&{sink:typeof sink;observer:WorkerObserver;directory:WorkerDirectory;control:WorkerControl})=>rest)({...options,sink,observer:stepObserver(sink),directory,control})):
   options.replayFrom!==undefined?await replayFrom(options.replayFrom,{...options,sink,observer:stepObserver(sink),stateStore:store!,directory,control}):
   await freshRun(options,spec,scenario,binding,store!,sink);
  if(result.status!=='CANCELLED')sink.emit(result.status==='FAILED'?'run.failed':'run.completed',{status:result.status,worker_outcomes:result.worker_outcomes,synthesis_invoked:result.synthesis_invoked,brief:result.brief,failure_code:result.failure_code,peak_concurrency:result.peak_concurrency});
  return result;
 }finally{sink.flush();}
}
