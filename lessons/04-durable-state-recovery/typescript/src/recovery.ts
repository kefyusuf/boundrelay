import {WORKER_IDS,type Brief,type CanonicalOutcomes,type CaseSpec,type RunResult,type RunStateDocument,type StateBinding,type WorkerControl,type WorkerDirectory,type WorkerId,type WorkerLifecycle,type WorkerObserver,type WorkerOutcome,type WorkerOutput} from './types.js';
import {validateRunResult} from './schemas.js';
import {executeWorkers} from './executor.js';
import {StateStore,loadRunState,loadRunStateDocument} from './state-store.js';
import {canonicalizeOutcomes} from './collector.js';
import {synthesizeBrief} from './synthesizer.js';
import {loadScenario} from './scenario.js';
export interface RecoverySink {emit(type:string,data:Record<string,unknown>):void}
export interface RunOptions {caseId:string;tracePath:string;stateDir:string;resume?:boolean;replayFrom?:string;sink?:RecoverySink;directory?:WorkerDirectory;control?:WorkerControl;synthesizer?:(orderId:string,outcomes:CanonicalOutcomes)=>Brief;stateStore?:StateStore;observer?:WorkerObserver;on_crash?:()=>never}
function emitCheckpointSaved(sink:RecoverySink|undefined,binding:StateBinding,store:StateStore,workerId:WorkerId):void {
 if(sink===undefined)return;
 const document=store.state();
 sink.emit('checkpoint.saved',{case_id:binding.case_id,execution_mode:binding.execution_mode,requested_order_id:binding.requested_order_id,concurrency_limit:binding.concurrency_limit,step_name:workerId,state_status:document.status,sequence_cursor:document.sequence_cursor});
}
export function recordedWorkerIds(document:RunStateDocument):WorkerId[] {return document.steps.filter(step=>step.status==='SUCCEEDED'||step.status==='FAILED').map(step=>step.worker_id);}
export function recordedOutcomes(document:RunStateDocument):WorkerOutcome[] {
 return document.steps.filter(step=>step.status==='SUCCEEDED'||step.status==='FAILED').map(step=>({worker_id:step.worker_id,status:step.status,output:structuredClone(step.output) as WorkerOutput|null,failure_code:step.failure_code}) as WorkerOutcome);
}
export function derivePending(document:RunStateDocument):WorkerId[] {
 const statuses=new Map(document.steps.map(step=>[step.worker_id,step.status]));
 return [...WORKER_IDS].filter(id=>['PENDING','RUNNING','CANCELLED'].includes(statuses.get(id)!));
}
function resolveCase(caseId:string):{spec:CaseSpec;binding:StateBinding} {
 const scenario=loadScenario();const spec=scenario.cases.find(entry=>entry.case_id===caseId);
 if(spec===undefined)throw new Error('Unknown case');
 return {spec,binding:{case_id:spec.case_id,execution_mode:spec.execution_mode,requested_order_id:scenario.order_id,concurrency_limit:spec.execution_mode==='sequential'?1:2}};
}
function requireResumable(document:RunStateDocument):void {
 if(document.status!=='RUNNING'&&document.status!=='CANCELLED')throw new Error(`Run state is not resumable (run_id=${document.run_id} status=${document.status})`);
}
function emitRestored(sink:RecoverySink,binding:StateBinding,document:RunStateDocument):void {
 sink.emit('checkpoint.restored',{case_id:binding.case_id,execution_mode:binding.execution_mode,requested_order_id:binding.requested_order_id,concurrency_limit:binding.concurrency_limit,state_status:document.status,restored_cursor:document.sequence_cursor,restored_worker_ids:recordedWorkerIds(document)});
}
async function completeRecoveredRun(store:StateStore,options:RunOptions,binding:StateBinding,document:RunStateDocument):Promise<RunResult> {
 if((options.directory===undefined)!==(options.control===undefined))throw new Error('Override pair required');
 const wrapped:WorkerObserver=event=>{
  options.observer?.(event);
  if(event.kind==='terminal')emitCheckpointSaved(options.sink,binding,store,event.outcome.worker_id);
 };
 const summary=await executeWorkers({mode:binding.execution_mode,input:{order_id:binding.requested_order_id},directory:options.directory!,control:options.control!,observer:wrapped,store,queue:derivePending(document)});
 const restored=new Map(recordedOutcomes(document).map(outcome=>[outcome.worker_id,outcome]));
 const fresh=new Map(summary.outcomes.map(outcome=>[outcome.worker_id,outcome]));
 const canonical=canonicalizeOutcomes(WORKER_IDS.map(id=>restored.get(id)??fresh.get(id)),binding.requested_order_id);
 const succeeded=canonical.filter(outcome=>outcome.status==='SUCCEEDED').length;
 const status=succeeded===3?'SUCCEEDED':succeeded===0?'FAILED':'PARTIAL';
 const failureCode=status==='FAILED'?'ALL_WORKERS_FAILED':null;
 let brief:Brief|null=null,synthesisInvoked=false;
 if(succeeded>0){
  options.sink?.emit('step.started',{step_name:'synthesize',worker_outcomes:canonical});
  brief=(options.synthesizer??synthesizeBrief)(binding.requested_order_id,canonical);synthesisInvoked=true;
  options.sink?.emit('step.completed',{step_name:'synthesize',brief});
 }
 if(failureCode===null)store.markTerminal(status);else store.markTerminal(status,failureCode);
 const result:RunResult={schema_version:'1.0',run_id:store.state().run_id,scenario_id:'order-brief-recovery',case_id:binding.case_id,execution_mode:binding.execution_mode,concurrency_limit:binding.concurrency_limit,peak_concurrency:Math.max(summary.peakConcurrency,1),order_id:binding.requested_order_id,status,worker_outcomes:canonical,synthesis_invoked:synthesisInvoked,brief,failure_code:failureCode,trace_path:options.tracePath,resumed:true,restored_cursor:document.sequence_cursor,restored_worker_ids:recordedWorkerIds(document),state_dir:options.stateDir,run_state_status:status};
 if(!validateRunResult(result))throw new Error('Invalid recovery result');
 return result;
}
export async function resumeRun(options:RunOptions):Promise<RunResult> {
 const {binding}=resolveCase(options.caseId);
 const loaded=loadRunState(options.stateDir,binding);
 requireResumable(loaded.document);
 emitRestored(options.sink??{emit:()=>{}},binding,loaded.document);
 const store=options.stateStore??StateStore.resume(loaded.document,loaded.restored_from);
 return completeRecoveredRun(store,options,binding,loaded.document);
}
export async function replayFrom(snapshotPath:string,options:RunOptions):Promise<RunResult> {
 const {binding}=resolveCase(options.caseId);
 const document=loadRunStateDocument(snapshotPath,binding);
 requireResumable(document);
 emitRestored(options.sink??{emit:()=>{}},binding,document);
 const store=options.stateStore??(():StateStore=>{const created=StateStore.create(options.stateDir,binding,[...WORKER_IDS]);for(const outcome of recordedOutcomes(document))created.recordStepTerminal(outcome.worker_id,outcome);return created;})();
 return completeRecoveredRun(store,options,binding,store.state());
}
