import {randomUUID} from 'node:crypto';
import {loadScenario} from './scenario.js';import {ScriptedWorkers} from './scripted-workers.js';import {createWorkerDirectory} from './workers.js';import {executeWorkers} from './executor.js';import {canonicalizeOutcomes} from './collector.js';import {synthesizeBrief} from './synthesizer.js';import {TraceSink} from './trace.js';import {validateRunResult} from './schemas.js';
import type {WorkerDirectory,WorkerControl,ExecutionMode,RunResult} from './types.js';
export interface RunOptions {caseId:string;tracePath:string;mode?:ExecutionMode;directory?:WorkerDirectory;control?:WorkerControl;synthesizer?:typeof synthesizeBrief}
export async function runCase(options:RunOptions):Promise<RunResult>{
 const scenario=loadScenario(),spec=scenario.cases.find(c=>c.case_id===options.caseId);
 if(spec===undefined||!options.tracePath||(options.mode!==undefined&&options.mode!==spec.execution_mode))throw new Error('Unknown case or incompatible mode');
 if((options.directory===undefined)!==(options.control===undefined))throw new Error('Directory and control must be supplied together');
 const provider=new ScriptedWorkers(spec,scenario.order_id),runId=randomUUID(),sink=new TraceSink(runId,options.tracePath);
 const context={scenario_id:'order-brief',case_id:spec.case_id,execution_mode:spec.execution_mode,order_id:scenario.order_id,concurrency_limit:spec.execution_mode==='sequential'?1:2};
 try{
  sink.emit('run.created',context);sink.emit('run.started',context);
  const execution=await executeWorkers({mode:spec.execution_mode,input:{order_id:scenario.order_id},directory:options.directory??createWorkerDirectory(provider),control:options.control??provider,observer:event=>{
   if(event.kind==='started')sink.emit('step.started',{step_name:'worker.'+event.worker_id,worker_id:event.worker_id,order_id:event.input.order_id});
   else sink.emit(event.outcome.status==='SUCCEEDED'?'step.completed':'step.failed',{step_name:'worker.'+event.outcome.worker_id,outcome:event.outcome});
  }});
  const outcomes=canonicalizeOutcomes(execution.outcomes,scenario.order_id),successes=outcomes.filter(o=>o.status==='SUCCEEDED').length;
  if(successes)sink.emit('step.started',{step_name:'synthesize',worker_outcomes:outcomes});
  const brief=successes?(options.synthesizer??synthesizeBrief)(scenario.order_id,outcomes):null;
  const result:RunResult={schema_version:'1.0',run_id:runId,scenario_id:'order-brief',case_id:spec.case_id,execution_mode:spec.execution_mode,concurrency_limit:context.concurrency_limit,peak_concurrency:execution.peakConcurrency,order_id:scenario.order_id,status:successes===3?'SUCCEEDED':successes?'PARTIAL':'FAILED',worker_outcomes:outcomes,synthesis_invoked:successes>0,brief,failure_code:successes?null:'ALL_WORKERS_FAILED',trace_path:options.tracePath};
  if(!validateRunResult(result))throw new Error('Invalid run result');
  if(successes)sink.emit('step.completed',{step_name:'synthesize',brief});
  sink.emit(successes?'run.completed':'run.failed',{status:result.status,worker_outcomes:outcomes,synthesis_invoked:result.synthesis_invoked,brief,failure_code:result.failure_code,peak_concurrency:result.peak_concurrency});
  return result;
 }finally{sink.flush();}
}
