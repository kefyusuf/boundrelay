import {loadScenario} from './scenario.js';import {ScriptedWorkers} from './scripted-workers.js';import {createWorkerDirectory} from './workers.js';import {executeWorkers} from './executor.js';import {TraceSink} from './trace.js';import {validateRunResult} from './schemas.js';import {StateStore,loadRunState} from './state-store.js';import {resumeRun} from './recovery.js';import {EffectLedger} from './effect-ledger.js';import {AuditWriter} from './audit.js';import {ApprovalGate} from './approval.js';
import {WORKER_IDS} from './types.js';
import type {ApprovalDecision,CaseSpec,EffectConfirmation,EffectStatus,EventSink,FailureCode,ResultStatus,RunResult,RunStateDocument,Scenario,StateBinding,WorkerControl,WorkerDirectory,WorkerId,WorkerObserver,WorkerOutcome} from './types.js';
export interface RunOptions {caseId:string;tracePath:string;stateDir:string;resume?:boolean;sink?:(EventSink&{flush:()=>void})|undefined;directory?:WorkerDirectory|undefined;control?:WorkerControl|undefined;stateStore?:StateStore|undefined;observer?:WorkerObserver|undefined;on_crash?:(()=>never)|undefined}
type Sink=EventSink&{flush:()=>void};
function recordedReads(document:{steps:{worker_id:WorkerId;status:string;output:unknown;failure_code:string|null}[]}):WorkerOutcome[] {
 return document.steps.filter(step=>step.status==='SUCCEEDED'||step.status==='FAILED').map(step=>({worker_id:step.worker_id,status:step.status,output:structuredClone(step.output),failure_code:step.failure_code}) as WorkerOutcome);
}
function stepObserver(sink:Sink):WorkerObserver {
 return event=>{
  if(event.kind==='started')sink.emit('step.started',{step_name:'worker.'+event.worker_id,worker_id:event.worker_id,order_id:event.input.order_id});
  else sink.emit(event.outcome.status==='SUCCEEDED'?'step.completed':'step.failed',{step_name:'worker.'+event.outcome.worker_id,outcome:event.outcome});
 };
}
function observerFor(sink:Sink,binding:StateBinding,store:StateStore,extra?:WorkerObserver):WorkerObserver {
 const step=stepObserver(sink);
 return event=>{
  extra?.(event);
  step(event);
  if(event.kind==='terminal'){
   const document=store.state();
   sink.emit('checkpoint.saved',{case_id:binding.case_id,execution_mode:binding.execution_mode,requested_order_id:binding.requested_order_id,concurrency_limit:binding.concurrency_limit,step_name:event.outcome.worker_id,state_status:document.status,sequence_cursor:document.sequence_cursor});
  }
 };
}
function effectWiring(options:RunOptions,spec:CaseSpec,sink:Sink,controls?:CaseSpec['controls']):{ledger:EffectLedger;approvalGate:ApprovalGate;audit:AuditWriter;controls?:CaseSpec['controls'];on_crash:()=>never;events:Sink} {
 return {ledger:new EffectLedger(options.stateDir),approvalGate:new ApprovalGate(spec.approval),audit:new AuditWriter(options.stateDir),
  ...(controls!==undefined?{controls}:{}),on_crash:options.on_crash??(()=>{sink.flush();process.exit(2);}),events:sink};
}
function assemble(options:RunOptions,binding:StateBinding,runId:string,peak:number,status:ResultStatus,reads:readonly WorkerOutcome[],decision:ApprovalDecision,effect:EffectConfirmation|null,effectStatus:EffectStatus,key:string|null,failureCode:FailureCode,reconciled:boolean,resumed:boolean,restoredCursor:number|null,restoredWorkerIds:WorkerId[]):RunResult {
 const canonical=WORKER_IDS.map(id=>reads.find(outcome=>outcome.worker_id===id)) as unknown as RunResult['worker_outcomes'];
 return {schema_version:'1.0',run_id:runId,scenario_id:'order-closure',case_id:binding.case_id,execution_mode:binding.execution_mode,concurrency_limit:binding.concurrency_limit,peak_concurrency:Math.max(peak,1),order_id:binding.requested_order_id,status,worker_outcomes:canonical,synthesis_invoked:false,brief:null,failure_code:failureCode,approval_decision:decision,effect_status:effectStatus,idempotency_key:key,reconciled,trace_path:options.tracePath,resumed,restored_cursor:restoredCursor,restored_worker_ids:restoredWorkerIds,state_dir:options.stateDir,run_state_status:status};
}
function finish(store:StateStore,sink:Sink,status:ResultStatus,failureCode:FailureCode,result:RunResult):RunResult {
 if(status==='FAILED')store.markTerminal('FAILED',failureCode??'ALL_WORKERS_FAILED');else store.markTerminal(status);
 return publish(sink,result);
}
function publish(sink:Sink,result:RunResult):RunResult {
 if(!validateRunResult(result))throw new Error('Invalid run result');
 sink.emit(result.status==='FAILED'?'run.failed':'run.completed',{status:result.status,worker_outcomes:result.worker_outcomes,synthesis_invoked:false,brief:null,failure_code:result.failure_code,peak_concurrency:result.peak_concurrency,reconciled:result.reconciled,approval_decision:result.approval_decision,effect_status:result.effect_status,idempotency_key:result.idempotency_key});
 return result;
}
async function resumedRun(options:RunOptions,spec:CaseSpec,scenario:Scenario,binding:StateBinding,loaded:{document:RunStateDocument;restored_from:string},sink:Sink):Promise<RunResult> {
 const document=loaded.document;
 const resumedStore=StateStore.resume(document,loaded.restored_from);
 const statuses=new Map(document.steps.map(step=>[step.worker_id,step.status]));
 const pending=WORKER_IDS.filter(id=>['PENDING','RUNNING','CANCELLED'].includes(statuses.get(id)!));
 let peak=1;
 if(pending.length){
  const resumeSpec:CaseSpec={...spec,execution_mode:pending.length>1?spec.execution_mode:'sequential',completion_order:spec.completion_order.filter(id=>pending.includes(id))};
  const provider=options.directory===undefined?new ScriptedWorkers(resumeSpec,scenario.order_id):undefined;
  const execution=await executeWorkers({mode:resumeSpec.execution_mode,input:{order_id:scenario.order_id},directory:options.directory??createWorkerDirectory(provider!),control:options.control??provider!,observer:observerFor(sink,binding,resumedStore,options.observer),store:resumedStore,queue:pending,completion_order:[...resumeSpec.completion_order]});
  peak=Math.max(execution.peakConcurrency,1);
 }
 const restoredCursor=document.sequence_cursor,restoredWorkerIds=document.steps.filter(step=>step.status==='SUCCEEDED'||step.status==='FAILED').map(step=>step.worker_id);
 const current=resumedStore.state(),reads=recordedReads(current),successes=reads.filter(o=>o.status==='SUCCEEDED').length;
 if(current.effect!==null||current.submit_marker!==null){
  const recovery=resumeRun({stateRoot:options.stateDir,binding,ledger:new EffectLedger(options.stateDir),audit:new AuditWriter(options.stateDir),...(spec.controls?.sink_unavailable===true?{controls:{sink_unavailable:true}}:{})});
  const status:ResultStatus=recovery.status==='UNKNOWN'?'UNKNOWN':'SUCCEEDED';
  const effectStatus:EffectStatus=status==='UNKNOWN'?'EFFECT_UNPROVABLE':recovery.effect?.status??null;
  const result=assemble(options,binding,resumedStore.state().run_id,peak,status,reads,'granted',recovery.effect,effectStatus,recovery.idempotency_key,null,recovery.reconciled,true,restoredCursor,restoredWorkerIds);
  return publish(sink,result);
 }
 if(successes===3){
  const provider=new ScriptedWorkers(spec,scenario.order_id);
  const execution=await executeWorkers({mode:'sequential',input:{order_id:scenario.order_id},directory:createWorkerDirectory(provider),control:provider,observer:stepObserver(sink),store:resumedStore,queue:[],completion_order:[...spec.completion_order],effect:effectWiring(options,spec,sink)});
  const effect=execution.effect!;
  const result=assemble(options,binding,resumedStore.state().run_id,Math.max(execution.peakConcurrency,1),'SUCCEEDED',reads,'granted',effect,'EFFECT_COMPLETED',effect.key,null,false,true,restoredCursor,restoredWorkerIds);
  return finish(resumedStore,sink,'SUCCEEDED',null,result);
 }
 let status:ResultStatus;let failureCode:FailureCode;
 if(successes>0){status='PARTIAL';failureCode=null;}else{status='FAILED';failureCode='ALL_WORKERS_FAILED';}
 return finish(resumedStore,sink,status,failureCode,assemble(options,binding,resumedStore.state().run_id,peak,status,reads,'none',null,null,null,failureCode,false,true,restoredCursor,restoredWorkerIds));
}

async function freshRun(options:RunOptions,spec:CaseSpec,scenario:Scenario,binding:StateBinding,store:StateStore,sink:Sink):Promise<RunResult> {
 const provider=options.directory===undefined?new ScriptedWorkers(spec,scenario.order_id):undefined;
 const execution=await executeWorkers({mode:spec.execution_mode,input:{order_id:scenario.order_id},directory:options.directory??createWorkerDirectory(provider!),control:options.control??provider!,observer:observerFor(sink,binding,store,options.observer),store,completion_order:[...spec.completion_order],effect:effectWiring(options,spec,sink,spec.controls)});
 const reads=execution.reads,successes=reads.filter(o=>o.status==='SUCCEEDED').length;
 let status:ResultStatus,decision:ApprovalDecision,effect=execution.effect,effectStatus:EffectStatus=execution.effect?.status??null,key=execution.effect?.key??null,failureCode:FailureCode=null;
 if(successes===3&&execution.rejected){status='FAILED';decision='rejected';effect=null;effectStatus=null;key=null;failureCode='APPROVAL_REJECTED';}
 else if(successes===3){status='SUCCEEDED';decision='granted';}
 else if(successes>0){status='PARTIAL';decision='none';effect=null;effectStatus=null;key=null;}
 else{status='FAILED';decision='none';effect=null;effectStatus=null;key=null;failureCode='ALL_WORKERS_FAILED';}
 return finish(store,sink,status,failureCode,assemble(options,binding,store.state().run_id,execution.peakConcurrency,status,reads,decision,effect,effectStatus,key,failureCode,false,false,null,[]));
}
export async function runCase(options:RunOptions):Promise<RunResult>{
 const scenario=loadScenario(),spec=scenario.cases.find(c=>c.case_id===options.caseId);
 if(spec===undefined||!options.tracePath||!options.stateDir)throw new Error('Unknown case or missing options');
 if((options.directory===undefined)!==(options.control===undefined))throw new Error('Directory and control must be supplied together');
 const binding:StateBinding={case_id:spec.case_id,execution_mode:spec.execution_mode,requested_order_id:scenario.order_id,concurrency_limit:spec.execution_mode==='sequential'?1:2};
 const context={scenario_id:'order-closure',case_id:spec.case_id,execution_mode:spec.execution_mode,order_id:scenario.order_id,concurrency_limit:binding.concurrency_limit,state_dir:options.stateDir};
 const loaded=options.resume?loadRunState(options.stateDir,binding):undefined;
 const store=loaded?undefined:(options.stateStore??StateStore.create(options.stateDir,binding,[...WORKER_IDS]));
 const runId=loaded?loaded.document.run_id:store!.state().run_id;
 const created=new TraceSink(runId,options.tracePath);
 const sink=options.sink??created;
 try{
  sink.emit('run.created',context);sink.emit('run.started',context);
  const result=loaded?await resumedRun(options,spec,scenario,binding,loaded,sink):await freshRun(options,spec,scenario,binding,store!,sink);
  return result;
 }finally{sink.flush();}
}


