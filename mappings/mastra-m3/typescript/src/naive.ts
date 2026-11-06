/** The naive M3 Mastra workflow: uncapped dispatch, default propagation.
 *
 * This is the teaching regression, kept honest. It trusts Mastra's
 * defaults everywhere: all three branches dispatch at once with no
 * admission cap (proven by a three-way rendezvous barrier inside the
 * steps - with any admission cap this rendezvous would break), worker
 * returns are published unvalidated (an invalid output becomes a fact),
 * and a declared worker error propagates by default, failing the whole
 * workflow run. Its results are asserted to diverge from the closed
 * schema (concurrency_limit null, attribution null, arrival-ordered
 * sections).
 */
import {createStep,createWorkflow} from '@mastra/core/workflows';
import {randomUUID} from 'node:crypto';
import {loadCase,type RunCase} from './fixtures.js';
import {errorMessage,passthroughSchema,streamRunToTrace,WorkerExecutionError,type RunnableWorkflow} from './mapping.js';

/** Records how many workers actually overlapped (recorded, not
 * normalized): the naive run has no cap, so all three can overlap. */
export class UncappedLedger{
 private depth=0;
 private peakCount=0;
 enter():void{this.depth+=1;this.peakCount=Math.max(this.peakCount,this.depth);}
 exit():void{this.depth-=1;}
 get peak():number{return this.peakCount;}
}
export type NaiveSection={worker_id:string;output:unknown};
/** The deliberately schema-invalid naive result shape. */
export type NaiveResult={[key:string]:unknown;worker_outcomes:NaiveSection[];brief:{order_id:string;sections:NaiveSection[];missing_workers:string[];complete:boolean};peak_concurrency:number|null;concurrency_limit:number|null;status:string;synthesis_invoked:boolean;attribution:null};

export function buildNaiveWorkflow(executionCase:RunCase,ledger:UncappedLedger,runId:string,tracePath:string):RunnableWorkflow{
 let arrived=0;
 let release:() => void=() => undefined;
 const rendezvous=new Promise<void>(resolve=>{release=resolve;});
 const workerSteps=['order-details','payment-status','delivery-status'].map(id=>createStep({
  id:`worker.${id}`,
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema(),
  execute:async() => {
   ledger.enter();
   try{
    arrived+=1;
    // Proves the framework dispatched all three branches at once: with
    // any admission cap this rendezvous would break.
    if(arrived===3)release();
    await rendezvous;
    const instruction=executionCase.instructions[id] as {operation:string;output?:unknown};
    if(instruction.operation==='raise'){
     // Default propagation: no taxonomy handling, the declared error
     // fails the whole workflow run.
     throw new WorkerExecutionError('Declared worker failure');
    }
    // Published unvalidated: the naive defect.
    return {worker_id:id,status:'SUCCEEDED',output:structuredClone(instruction.output) as Record<string,unknown>,failure_code:null};
   }finally{ledger.exit();}
  }}));
 const synthesizeStep=createStep({
  id:'synthesize',
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema(),
  execute:async({inputData}) => {
   // The naive fan-in: no completion-order gates and no canonical
   // collector. Mastra hands the synthesize step the parallel output
   // keyed in step-definition order; the naive graph walks it as-is and
   // has no way to honor the fixture's scripted completion order - the
   // order is whatever the engine's composition dictates, not a
   // semantics the application chose.
   const sections=Object.values(inputData as Record<string,NaiveSection>)
    .map(section=>({worker_id:section.worker_id,output:section.output}));
   return {
    schema_version:'1.0',run_id:runId,scenario_id:'order-brief',case_id:executionCase.case_id,
    execution_mode:'parallel',concurrency_limit:null,peak_concurrency:ledger.peak,
    order_id:executionCase.order_id,status:'SUCCEEDED',
    worker_outcomes:sections.map(section=>({worker_id:section.worker_id,status:'SUCCEEDED',output:section.output,failure_code:null})),
    synthesis_invoked:true,
    brief:{order_id:executionCase.order_id,sections,missing_workers:[],complete:true},
    failure_code:null,trace_path:tracePath,attribution:null} satisfies NaiveResult;
  }});
 return createWorkflow({
  id:'order-brief-naive-mapping',
  inputSchema:passthroughSchema(),
  outputSchema:passthroughSchema()})
  .parallel(workerSteps)
  .then(synthesizeStep)
  .commit() as unknown as RunnableWorkflow;
}

/** Run one assembled case through the naive workflow, streaming the
 * native stream to the trace file. Declared worker errors propagate
 * (exit-path 2); the flushed stream prefix stays inspectable. */
export async function runNaiveCase(executionCase:RunCase,tracePath:string):Promise<NaiveResult>{
 const ledger=new UncappedLedger();
 const workflow=buildNaiveWorkflow(executionCase,ledger,randomUUID(),tracePath);
 const outcome=await streamRunToTrace(workflow,tracePath);
 if(outcome.status!=='success'){
  throw new Error(errorMessage(outcome.error??'naive run failed'));
 }
 return outcome.result as NaiveResult;
}

/** Load one parity case and run it through the naive workflow. */
export async function runNaive(caseId:string,tracePath:string):Promise<NaiveResult>{
 return runNaiveCase(loadCase(caseId),tracePath);
}
