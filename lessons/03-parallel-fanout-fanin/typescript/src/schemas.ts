import {readFileSync} from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import {ROOT} from './paths.js';
import type {WorkerId,WorkerOutput,WorkerOutcome,ValidationResult,RunResult} from './types.js';
const ajv=new Ajv2020({strict:false});addFormats(ajv);
const load=(path:string)=>JSON.parse(readFileSync(ROOT+'/'+path,'utf8'));
const worker=ajv.compile(load('contracts/workers/order-brief-worker-result.schema.json'));
const result=ajv.compile(load('contracts/results/order-brief-result.schema.json'));
export const eventValidator=ajv.compile(load('contracts/events/run-event.schema.json'));
export function finiteJson(value:unknown,seen=new Set<object>(),depth=0):boolean {
 if(depth>32)return false;
 if(value===null||typeof value==='string'||typeof value==='boolean')return true;
 if(typeof value==='number')return Number.isFinite(value)&&(!Number.isInteger(value)||Number.isSafeInteger(value));
 if(typeof value!=='object'||seen.has(value))return false;
 if(!Array.isArray(value)&&Object.getPrototypeOf(value)!==Object.prototype)return false;
 seen.add(value);try{return Object.values(value).every(v=>finiteJson(v,seen,depth+1));}finally{seen.delete(value);}
}
export function validateWorkerOutput(id:WorkerId,raw:unknown,orderId:string):ValidationResult<WorkerOutput> {
 if(!finiteJson(raw))return {valid:false};
 const candidate={worker_id:id,status:'SUCCEEDED',output:raw,failure_code:null};
 if(!worker(candidate)||(raw as WorkerOutput).order_id!==orderId)return {valid:false};
 return {valid:true,value:structuredClone(raw) as WorkerOutput};
}
export function validateWorkerOutcome(raw:unknown,orderId:string):raw is WorkerOutcome {
 return finiteJson(raw)&&Boolean(worker(raw))&&((raw as WorkerOutcome).output===null||(raw as WorkerOutcome).output?.order_id===orderId);
}
export function validateRunResult(raw:unknown):raw is RunResult {return finiteJson(raw)&&Boolean(result(raw));}
