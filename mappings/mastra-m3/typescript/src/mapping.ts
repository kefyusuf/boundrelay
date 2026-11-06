/** The corrected M3 Mastra workflow: taxonomy-preserving, canonically
 * ordered, bounded admission re-established inside the step wrapper.
 *
 * Topology (one workflow per case run):
 *   three worker steps in .parallel() -> collect -> .branch([synthesize])
 *   -> finalize. Each worker step is a Mastra Step whose execute() wraps a
 *   scripted worker: a declared error becomes a FAILED outcome with
 *   WORKER_EXECUTION_FAILED; an invalid return becomes FAILED with
 *   INVALID_WORKER_OUTPUT - both validated before publication. The
 *   framework's .parallel() dispatch is uncapped by default (proven by the
 *   naive 3-way rendezvous recording peak 3); the application re-establishes
 *   the 1/2-slot cap through BoundedWorkerExecutor inside the steps - the
 *   mapping's centerpiece cost. Canonical outcome ordering is structural:
 *   per-step outputs are keyed by step id and merged in WORKER_IDS order by
 *   the collect step (Mastra's shared workflow state is last-write-wins
 *   under parallel branches, so it cannot carry the fan-in).
 */
import {createStep,createWorkflow,type Step} from '@mastra/core/workflows';
import type {StandardSchemaWithJSON} from '@mastra/core/schema';
import {randomUUID} from 'node:crypto';
import {closeSync,mkdirSync,openSync,writeSync} from 'node:fs';
import {dirname} from 'node:path';
import {loadCase,WORKER_IDS,type RunCase} from './fixtures.js';
import {buildAttribution,type AttributionBlock} from './attribution.js';
import {assembleResult,canonicalizeOutcomes,synthesizeBrief,validateWorkerOutput,type Brief,type CanonicalOutcomes,type RunResult,type WorkerId,type WorkerOutcome,type WorkerOutput} from './results.js';

export class WorkerExecutionError extends Error{}
export class ToolingInterrupted extends Error{}

const DEFAULT_GUARD_MS=90_000;
type WorkflowOutcome={status:string;result:unknown;error?:unknown};
export type RunnableWorkflow={createRun:() => Promise<{stream:(input:{inputData:Record<string,unknown>}) => {fullStream:AsyncIterable<unknown>;result:Promise<WorkflowOutcome>}}>} & Record<string,unknown>;

/** The engine serializes a failed run's error as a plain object
 * ({message, name}); recover the message for tooling diagnostics. */
export function errorMessage(error:unknown):string{
 if(error instanceof Error)return error.message;
 if(error!==null&&typeof error==='object'&&typeof (error as {message?:unknown}).message==='string')return (error as {message:string}).message;
 return JSON.stringify(error)??String(error);
}

/** A dependency-free Standard Schema passthrough: identity validation and
 * an open object JSON schema. The mapping runs the Mastra workflow
 * engine schema-less on purpose - the closed M3 shapes are enforced by
 * results.ts (structural validators) before publication, not by
 * framework IO schemas. */
export function passthroughSchema():StandardSchemaWithJSON{
 const openObject:Record<string,unknown>={type:'object',additionalProperties:true};
 return {
  '~standard':{
   version:1,
   vendor:'boundrelay-mapping',
   validate:(value:unknown) => ({value}),
   jsonSchema:{
    input:() => openObject,
    output:() => openObject}}};
}

/** Write the native Mastra stream chunks verbatim (one JSON object per
 * line) to the trace file while the run executes; a failed run leaves a
 * flushed, inspectable prefix and no canonical result. */
export async function streamRunToTrace(workflow:RunnableWorkflow,tracePath:string):Promise<WorkflowOutcome>{
 mkdirSync(dirname(tracePath),{recursive:true});
 const handle=openSync(tracePath,'w');
 try{
  const run=await workflow.createRun();
  const stream=run.stream({inputData:{}});
  for await(const chunk of stream.fullStream){
   writeSync(handle,`${JSON.stringify(chunk)}\n`);
  }
  return await stream.result;
 }finally{
  closeSync(handle);
 }
}

/** The bounded executor wrapper re-establishing M3 admission caps.
 *
 * Mastra admits all .parallel() branch steps at once (uncapped; proven by
 * the naive 3-way rendezvous recording peak 3). This wrapper caps
 * concurrent workers at `limit` (2 for parallel, 1 for sequential),
 * admits in canonical worker order (so the fixture's completion order
 * stays feasible), releases workers along the fixture's completion_order
 * (a slot is occupied until the validated outcome is recorded), and
 * records the observed peak concurrency. The first parallel release
 * additionally waits for the whole first wave to have entered, proving
 * the cap binds. Deadlock guard: bounded waits reject with
 * ToolingInterrupted instead of hanging forever.
 */
export class BoundedWorkerExecutor{
 private readonly completionOrder:readonly string[];
 private readonly limit:1|2;
 private readonly guardMs:number;
 private readonly active=new Set<string>();
 private readonly entered=new Set<string>();
 private cursor=0;
 private peak=0;
 private broken=false;
 private readonly waiters:Waiter[]=[];
 constructor(completionOrder:readonly string[],limit:number,options?:{guardMs?:number}){
  if(limit!==1&&limit!==2)throw new Error('Admission limit must be 1 or 2');
  this.completionOrder=[...completionOrder];
  this.limit=limit as 1|2;
  this.guardMs=options?.guardMs??DEFAULT_GUARD_MS;
 }
 get observedPeak():number{return this.peak;}
 /** Occupy a slot: admitted only when a slot is free AND every
  * canonical-prior worker has already entered (canonical admission). */
 enter(workerId:string):Promise<void>{
  return this.waitAndRun(`enter(${workerId})`,()=>{
   const index=WORKER_IDS.indexOf(workerId as WorkerId);
   const priors=index<0?[]:WORKER_IDS.slice(0,index);
   if(this.active.size>=this.limit)return false;
   if(priors.some(id=>!this.entered.has(id)))return false;
   this.entered.add(workerId);
   this.active.add(workerId);
   this.peak=Math.max(this.peak,this.active.size);
   this.notify();
   return true;
  });
 }
 /** Completion-order gate: run your instruction on your turn. The first
  * parallel release additionally waits for the whole first wave to have
  * entered (proves the cap binds: peak >= limit). */
 awaitRelease(workerId:string):Promise<void>{
  return this.waitAndRun(`release(${workerId})`,()=>{
   if(this.completionOrder[this.cursor]!==workerId)return false;
   const firstWave=this.cursor===0&&this.limit===2&&WORKER_IDS.length>this.limit;
   const required=firstWave?Math.min(this.limit,WORKER_IDS.length):0;
   return this.entered.size>=required;
  });
 }
 /** Record the validated outcome: the slot frees, the gate advances. */
 record(workerId:string):void{
  if(!this.active.has(workerId))throw new Error(`record() without an active slot: ${workerId}`);
  this.active.delete(workerId);
  this.cursor+=1;
  this.notify();
 }
 /** Unexpected error path: drain the run and fail every waiter. */
 abandon(workerId:string):void{
  this.broken=true;
  this.active.delete(workerId);
  this.notify();
 }
 private waitAndRun(what:string,attempt:() => boolean):Promise<void>{
  return new Promise<void>((resolve,reject)=>{
   if(this.broken){reject(new ToolingInterrupted('Run drained by an unexpected error'));return;}
   if(attempt()){resolve();return;}
   const timer=setTimeout(()=>{
    const index=this.waiters.indexOf(waiter);
    if(index>=0)this.waiters.splice(index,1);
    reject(new ToolingInterrupted(`Admission guard tripped: ${what}`));
   },this.guardMs);
   const waiter:Waiter={attempt,settle:(error?)=>{clearTimeout(timer);if(error)reject(error);else resolve();},timer};
   this.waiters.push(waiter);
  });
 }
 private notify():void{
  for(const waiter of [...this.waiters]){
   const index=this.waiters.indexOf(waiter);
   if(this.broken){this.waiters.splice(index,1);waiter.settle(new ToolingInterrupted('Run drained by an unexpected error'));}
   else if(waiter.attempt()){this.waiters.splice(index,1);waiter.settle();}
  }
 }
}
type Waiter={attempt:() => boolean;settle:(error?:Error) => void;timer:NodeJS.Timeout};

/** Taxonomy-preserving failure handling INSIDE the step.
 *
 * Declared error -> FAILED/WORKER_EXECUTION_FAILED. Invalid return ->
 * FAILED/INVALID_WORKER_OUTPUT (validated before publication). Only
 * unexpected implementation errors escape the step.
 */
export function workerOutcome(workerId:WorkerId,instruction:unknown,orderId:string):WorkerOutcome{
 const i=instruction as {operation:string;output?:unknown};
 if(i.operation==='raise')throw new WorkerExecutionError('Declared worker failure');
 const validation=validateWorkerOutput(workerId,i.output,orderId);
 if(validation.valid)return {worker_id:workerId,status:'SUCCEEDED',output:validation.value as WorkerOutput,failure_code:null};
 return {worker_id:workerId,status:'FAILED',output:null,failure_code:'INVALID_WORKER_OUTPUT'};
}

function makeWorkerStep(workerId:WorkerId,executionCase:RunCase,executor:BoundedWorkerExecutor):Step{
 return createStep({
  id:`worker.${workerId}`,
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema(),
  execute:async() => {
   await executor.enter(workerId);
   await executor.awaitRelease(workerId);
   let outcome:WorkerOutcome;
   try{
    outcome=workerOutcome(workerId,executionCase.instructions[workerId] as {operation:string;output?:unknown},executionCase.order_id);
   }catch(error){
    if(!(error instanceof WorkerExecutionError)){executor.abandon(workerId);throw error;}
    outcome={worker_id:workerId,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'};
   }
   executor.record(workerId);
   return outcome;
  }});
}

/** Build the corrected Mastra workflow for one M3 case run. */
export function buildCorrectedWorkflow(executionCase:RunCase,executor:BoundedWorkerExecutor,runId:string,tracePath:string):RunnableWorkflow{
 const workerSteps=WORKER_IDS.map(id=>makeWorkerStep(id,executionCase,executor));
 const collectStep=createStep({
  id:'collect',
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema(),
  execute:async({inputData}) => {
   const parallel=inputData as Record<string,unknown>;
   const raw=WORKER_IDS.map(id=>parallel[`worker.${id}`]);
   return {outcomes:canonicalizeOutcomes(raw,executionCase.order_id)};
  }});
 const synthesizeStep=createStep({
  id:'synthesize',
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema(),
  execute:async({inputData}) => ({brief:synthesizeBrief(executionCase.order_id,(inputData as {outcomes:readonly WorkerOutcome[]}).outcomes as CanonicalOutcomes)})});
 const finalizeStep=createStep({
  id:'finalize',
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema(),
  execute:async({inputData,getStepResultAsync}) => {
   const collected=await getStepResultAsync(collectStep) as {outcomes:readonly WorkerOutcome[]};
   const brief=(inputData as Record<string,{brief:Brief}|undefined>)['synthesize']?.brief??null;
   const records:[string,number][]=WORKER_IDS.map(id=>[`worker.${id}`,1] as [string,number]);
   if(brief!==null)records.push(['synthesize',1]);
   const attribution:AttributionBlock=buildAttribution(records,{latency_ms:executionCase.latency_ms,price_table:executionCase.price_table});
   return assembleResult({run_id:runId,trace_path:tracePath,case:executionCase,peak_concurrency:executor.observedPeak as 1|2,outcomes:collected.outcomes,brief,attribution});
  }});
 return createWorkflow({
  id:'order-brief-mapping',
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema()})
  .parallel(workerSteps)
  .then(collectStep)
  .branch([[async({getStepResultAsync}) => {
   const collected=await getStepResultAsync(collectStep) as {outcomes:readonly WorkerOutcome[]};
   return collected.outcomes.some(o=>o.status==='SUCCEEDED');
  },synthesizeStep]])
  .then(finalizeStep)
  .commit() as unknown as RunnableWorkflow;
}

/** Run one M3 case through the corrected workflow, streaming the native
 * Mastra stream to the trace file; returns the published result. */
export async function runWorkflow(executionCase:RunCase,executor:BoundedWorkerExecutor,tracePath:string,runId:string):Promise<RunResult>{
 const workflow=buildCorrectedWorkflow(executionCase,executor,runId,tracePath);
 const outcome=await streamRunToTrace(workflow,tracePath);
 if(outcome.status!=='success'){
  throw new ToolingInterrupted(`Corrected run failed: ${errorMessage(outcome.error??'workflow failed')}`);
 }
 const published=outcome.result as unknown;
 if(published===null||typeof published!=='object'||!('worker_outcomes' in published))throw new ToolingInterrupted('Corrected run produced no publishable result');
 return published as RunResult;
}

/** Load one parity case and run it through the corrected workflow. */
export async function runCorrected(caseId:string,tracePath:string):Promise<RunResult>{
 const executionCase=loadCase(caseId);
 return runWorkflow(executionCase,new BoundedWorkerExecutor(executionCase.completion_order,executionCase.limit),tracePath,randomUUID());
}
