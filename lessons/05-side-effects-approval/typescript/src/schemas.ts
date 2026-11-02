import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import {ROOT} from './paths.js';
import type {AuditRecord,EffectOutcome,EffectPayload,LedgerRecord,RunResult,RunStateDocument,ValidationResult,WorkerId,WorkerOutput,WorkerOutcome} from './types.js';
const ajv=new Ajv2020({strict:false});addFormats(ajv);
const load=(path:string)=>JSON.parse(readFileSync(ROOT+'/'+path,'utf8'));
const worker=ajv.compile(load('contracts/workers/order-brief-worker-result.schema.json'));
const result=ajv.compile(load('contracts/results/order-closure-result.schema.json'));
const state=ajv.compile(load('contracts/state/order-closure-run-state.schema.json'));
const auditRecord=ajv.compile(load('contracts/audit/order-closure-audit.schema.json'));
const effectSchema=load('contracts/effects/order-closure-effect.schema.json');
const effectRecord=ajv.compile(effectSchema);
const effectPayload=ajv.compile(effectSchema.$defs.effectPayload);
const effectOutcome=ajv.compile(effectSchema.$defs.effectOutcome);
export const eventValidator=ajv.compile(load('contracts/events/run-event.schema.json'));
export function finiteJson(value:unknown,seen=new Set<object>(),depth=0):boolean {
 if(depth>32)return false;
 if(value===null||typeof value==='string'||typeof value==='boolean')return true;
 if(typeof value==='number')return Number.isFinite(value)&&(!Number.isInteger(value)||Number.isSafeInteger(value));
 if(typeof value!=='object'||seen.has(value))return false;
 if(!Array.isArray(value)&&Object.getPrototypeOf(value)!==Object.prototype)return false;
 const descriptors=Object.getOwnPropertyDescriptors(value);
 seen.add(value);try{return Reflect.ownKeys(value).every(key=>{
  if(typeof key!=='string')return false;
  if(Array.isArray(value)&&key==='length')return true;
  const descriptor=descriptors[key];
  return descriptor!==undefined&&descriptor.enumerable===true&&'value' in descriptor&&finiteJson(descriptor.value,seen,depth+1);
 });}finally{seen.delete(value);}
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
export function validateRunStateDocument(raw:unknown):ValidationResult<RunStateDocument> {
 if(!finiteJson(raw)||!state(raw))return {valid:false};
 return {valid:true,value:structuredClone(raw) as RunStateDocument};
}
export function validateEffectPayload(raw:unknown):ValidationResult<EffectPayload> {
 if(!finiteJson(raw)||!effectPayload(raw))return {valid:false};
 return {valid:true,value:structuredClone(raw) as EffectPayload};
}
export function validateEffectOutcome(raw:unknown):raw is EffectOutcome {
 return finiteJson(raw)&&effectOutcome(raw);
}
export function validateEffectRecord(raw:unknown):ValidationResult<LedgerRecord> {
 if(!finiteJson(raw)||!effectRecord(raw))return {valid:false};
 return {valid:true,value:structuredClone(raw) as LedgerRecord};
}
export function validateAuditRecord(raw:unknown):raw is AuditRecord {
 return finiteJson(raw)&&auditRecord(raw);
}
export function canonicalJson(value:unknown):string {
 if(value===null||typeof value!=='object')return JSON.stringify(value);
 if(Array.isArray(value))return `[${value.map(canonicalJson).join(',')}]`;
 const entries=Object.entries(value as Record<string,unknown>).sort(([a],[b])=>(a<b?-1:a>b?1:0));
 return `{${entries.map(([key,item])=>`${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`;
}
export function canonicalStateBody(document:RunStateDocument):string {
 const {digest:_digest,...body}=document;
 return canonicalJson(body);
}
export function stateDigest(body:string):string {return createHash('sha256').update(body,'utf8').digest('hex');}


