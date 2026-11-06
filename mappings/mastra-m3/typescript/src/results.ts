/** M3-schema-valid result assembly with structural validation.
 *
 * Mirrors the closed result schema (contracts/results/order-brief-result
 * .schema.json) by hand: exact field sets, enums, ORD pattern, canonical
 * worker_outcomes ordering, and the status conditionals. Attribution
 * totals must equal the sum of steps (stronger than the JSON schema).
 * The mapping runs the Mastra workflow schema-less: these validators are
 * the gate that keeps the closed M3 shapes intact before publication.
 */
import {WORKER_IDS} from './fixtures.js';
import type {AttributionBlock} from './attribution.js';

export type WorkerId=typeof WORKER_IDS[number];
export type WorkerOutput={order_id:string;order_status:'PROCESSING'|'SHIPPED'|'CANCELLED'}|{order_id:string;payment_status:'PAID'|'UNPAID'}|{order_id:string;delivery_status:'PENDING'|'IN_TRANSIT'|'DELIVERED'|'DELAYED'};
export type WorkerOutcome={worker_id:WorkerId;status:'SUCCEEDED';output:WorkerOutput;failure_code:null}|{worker_id:WorkerId;status:'FAILED';output:null;failure_code:'WORKER_EXECUTION_FAILED'|'INVALID_WORKER_OUTPUT'};
export type CanonicalOutcomes=readonly [WorkerOutcome,WorkerOutcome,WorkerOutcome];
export type Brief={order_id:string;sections:{worker_id:WorkerId;output:WorkerOutput}[];missing_workers:WorkerId[];complete:boolean};
export type RunResult={schema_version:'1.0';run_id:string;scenario_id:'order-brief';case_id:string;execution_mode:'sequential'|'parallel';concurrency_limit:1|2;peak_concurrency:1|2;order_id:string;status:'SUCCEEDED'|'PARTIAL'|'FAILED';worker_outcomes:CanonicalOutcomes;synthesis_invoked:boolean;brief:Brief|null;failure_code:'ALL_WORKERS_FAILED'|null;trace_path:string;attribution:AttributionBlock};
export type CaseForAssembly={case_id:string;execution_mode:'sequential'|'parallel';order_id:string;limit:1|2};

const RESULT_FIELDS=Object.freeze(['attribution','brief','case_id','concurrency_limit','execution_mode','failure_code','order_id','peak_concurrency','run_id','schema_version','scenario_id','status','synthesis_invoked','trace_path','worker_outcomes']);
const OUTCOME_FIELDS=Object.freeze(['failure_code','output','status','worker_id']);
const SECTION_FIELDS=Object.freeze(['output','worker_id']);
const BRIEF_FIELDS=Object.freeze(['complete','missing_workers','order_id','sections']);
const WORKER_FAILURE_CODES=Object.freeze(['WORKER_EXECUTION_FAILED','INVALID_WORKER_OUTPUT']);
const WORKER_OUTPUT_FIELDS:Record<string,{field:'order_status'|'payment_status'|'delivery_status';allowed:readonly string[]}>={
 'order-details':{field:'order_status',allowed:['PROCESSING','SHIPPED','CANCELLED']},
 'payment-status':{field:'payment_status',allowed:['PAID','UNPAID']},
 'delivery-status':{field:'delivery_status',allowed:['PENDING','IN_TRANSIT','DELIVERED','DELAYED']}};

export function finiteJson(value:unknown,seen:Set<object>=new Set<object>(),depth=0):boolean{
 if(depth>32)return false;
 if(value===null||typeof value==='string'||typeof value==='boolean')return true;
 if(typeof value==='number')return Number.isFinite(value)&&(!Number.isInteger(value)||Number.isSafeInteger(value));
 if(typeof value!=='object'||seen.has(value))return false;
 if(!Array.isArray(value)&&Object.getPrototypeOf(value)!==Object.prototype)return false;
 const descriptors=Object.getOwnPropertyDescriptors(value);
 seen.add(value);
 try{
  return Reflect.ownKeys(value).every(key=>{
   if(typeof key!=='string')return false;
   if(Array.isArray(value)&&key==='length')return true;
   const descriptor=descriptors[key];
   return descriptor!==undefined&&descriptor.enumerable===true&&'value' in descriptor&&finiteJson(descriptor.value,seen,depth+1);
  });
 }finally{seen.delete(value);}
}
const isOrd=(value:unknown):boolean=>typeof value==='string'&&/^ORD-[0-9]{4}$/.test(value);

export function validateWorkerOutput(workerId:WorkerId,raw:unknown,orderId:string):{valid:boolean;value?:WorkerOutput}{
 if(!finiteJson(raw)||raw===null||typeof raw!=='object'||Array.isArray(raw))return {valid:false};
 const candidate=raw as Record<string,unknown>;
 if(candidate['order_id']!==orderId)return {valid:false};
 const spec=WORKER_OUTPUT_FIELDS[workerId];
 if(spec===undefined)return {valid:false};
 if(Object.keys(candidate).sort().join('|')!==['order_id',spec.field].sort().join('|'))return {valid:false};
 if(candidate[spec.field]===undefined||!(spec.allowed as readonly unknown[]).includes(candidate[spec.field]))return {valid:false};
 return {valid:true,value:structuredClone(raw) as WorkerOutput};
}
function validSuccessOutcome(outcome:Record<string,unknown>,orderId:string):boolean{
 const workerId=outcome['worker_id'];
 if(typeof workerId!=='string'||!(WORKER_IDS as readonly string[]).includes(workerId))return false;
 const output=outcome['output'];
 if(output===null||typeof output!=='object'||Array.isArray(output))return false;
 return validateWorkerOutput(workerId as WorkerId,output,orderId).valid&&outcome['failure_code']===null;
}
export function validateWorkerOutcome(raw:unknown,orderId:string):boolean{
 if(!finiteJson(raw)||raw===null||typeof raw!=='object'||Array.isArray(raw))return false;
 const outcome=raw as Record<string,unknown>;
 if(Object.keys(outcome).sort().join('|')!==OUTCOME_FIELDS.join('|'))return false;
 if(!(WORKER_IDS as readonly string[]).includes(outcome['worker_id'] as string))return false;
 if(outcome['status']==='SUCCEEDED')return validSuccessOutcome(outcome,orderId);
 if(outcome['status']==='FAILED')return outcome['output']===null&&(WORKER_FAILURE_CODES as readonly unknown[]).includes(outcome['failure_code']);
 return false;
}
export function canonicalizeOutcomes(raw:readonly unknown[],orderId:string):CanonicalOutcomes{
 if(!Array.isArray(raw)||raw.length!==3||!raw.every(o=>validateWorkerOutcome(o,orderId)))throw new Error('Incomplete or invalid fan in');
 const outcomes=raw as readonly WorkerOutcome[];
 if(new Set(outcomes.map(o=>o.worker_id)).size!==3)throw new Error('Duplicate worker identity');
 return WORKER_IDS.map(id=>structuredClone(outcomes.find(o=>o.worker_id===id)!)) as unknown as CanonicalOutcomes;
}
export function synthesizeBrief(orderId:string,outcomes:CanonicalOutcomes):Brief{
 const canonical=canonicalizeOutcomes(outcomes,orderId);
 const sections=canonical.flatMap(o=>o.status==='SUCCEEDED'?[{worker_id:o.worker_id,output:o.output}]:[]);
 if(sections.length===0)throw new Error('Cannot synthesize without successful evidence');
 const missingWorkers=canonical.filter(o=>o.status==='FAILED').map(o=>o.worker_id);
 return {order_id:orderId,sections,missing_workers:missingWorkers,complete:missingWorkers.length===0};
}
const isIntAtLeast=(value:unknown,minimum:number):boolean=>typeof value==='number'&&Number.isInteger(value)&&value>=minimum;

function validBrief(brief:unknown,orderId:string,expectedComplete:boolean):boolean{
 if(brief===null||typeof brief!=='object'||Array.isArray(brief))return false;
 const b=brief as Record<string,unknown>;
 if(Object.keys(b).sort().join('|')!==BRIEF_FIELDS.join('|'))return false;
 if(b['order_id']!==orderId||typeof b['complete']!=='boolean'||b['complete']!==expectedComplete)return false;
 const sections=b['sections'];
 if(!Array.isArray(sections)||sections.length<1||sections.length>3)return false;
 for(const section of sections){
  if(section===null||typeof section!=='object'||Array.isArray(section))return false;
  const s=section as Record<string,unknown>;
  if(Object.keys(s).sort().join('|')!==SECTION_FIELDS.join('|'))return false;
  if(!validSuccessOutcome({worker_id:s['worker_id'],output:s['output'],failure_code:null},orderId))return false;
 }
 const missing=b['missing_workers'];
 if(!Array.isArray(missing)||missing.length>2||new Set(missing).size!==missing.length||missing.some(id=>!(WORKER_IDS as readonly string[]).includes(id as string)))return false;
 const succeededIds=new Set(sections.map(s=>(s as Record<string,unknown>)['worker_id']));
 const failedIds=WORKER_IDS.filter(id=>!succeededIds.has(id));
 return missing.length===failedIds.length&&failedIds.every(id=>missing.includes(id));
}
function validAttribution(attribution:unknown):boolean{
 if(attribution===null||typeof attribution!=='object'||Array.isArray(attribution))return false;
 const a=attribution as Record<string,unknown>;
 if(Object.keys(a).sort().join('|')!=='steps|totals')return false;
 const steps=a['steps'];
 if(!Array.isArray(steps)||steps.length===0)return false;
 for(const step of steps){
  if(step===null||typeof step!=='object'||Array.isArray(step))return false;
  const s=step as Record<string,unknown>;
  if(Object.keys(s).sort().join('|')!=='attempts|cost_cents|latency_ms|step_name')return false;
  if(typeof s['step_name']!=='string'||s['step_name']===''||!isIntAtLeast(s['latency_ms'],0)||!isIntAtLeast(s['cost_cents'],0)||!isIntAtLeast(s['attempts'],1))return false;
 }
 const totals=a['totals'];
 if(totals===null||typeof totals!=='object'||Array.isArray(totals))return false;
 const t=totals as Record<string,unknown>;
 if(Object.keys(t).sort().join('|')!=='attempts|cost_cents|latency_ms')return false;
 const stepsList=steps as Record<string,unknown>[];
 const sums={latency_ms:stepsList.reduce((acc,s)=>acc+(s['latency_ms'] as number),0),cost_cents:stepsList.reduce((acc,s)=>acc+(s['cost_cents'] as number),0),attempts:stepsList.reduce((acc,s)=>acc+(s['attempts'] as number),0)};
 return t['latency_ms']===sums.latency_ms&&t['cost_cents']===sums.cost_cents&&t['attempts']===sums.attempts;
}
function validStatusShape(result:Record<string,unknown>):boolean{
 const outcomes=result['worker_outcomes'];
 if(!Array.isArray(outcomes)||outcomes.length!==3)return false;
 const orderId=result['order_id'] as string;
 if(!outcomes.every(o=>validateWorkerOutcome(o,orderId)))return false;
 if(outcomes.map(o=>(o as WorkerOutcome).worker_id).join('|')!==WORKER_IDS.join('|'))return false;
 const successes=outcomes.filter(o=>(o as WorkerOutcome).status==='SUCCEEDED').length;
 if(result['status']==='SUCCEEDED'&&successes===3)return result['synthesis_invoked']===true&&result['failure_code']===null&&validBrief(result['brief'],orderId,true);
 if(result['status']==='PARTIAL'&&successes>=1&&successes<=2)return result['synthesis_invoked']===true&&result['failure_code']===null&&validBrief(result['brief'],orderId,false);
 if(result['status']==='FAILED'&&successes===0)return result['synthesis_invoked']===false&&result['failure_code']==='ALL_WORKERS_FAILED'&&result['brief']===null;
 return false;
}
export function validateResult(result:unknown):boolean{
 if(!finiteJson(result)||result===null||typeof result!=='object'||Array.isArray(result))return false;
 const r=result as Record<string,unknown>;
 if(Object.keys(r).length!==RESULT_FIELDS.length||Object.keys(r).some(k=>!RESULT_FIELDS.includes(k)))return false;
 if(r['schema_version']!=='1.0'||r['scenario_id']!=='order-brief'||!isOrd(r['order_id'])
  ||typeof r['run_id']!=='string'||r['run_id']===''||typeof r['case_id']!=='string'||r['case_id']===''
  ||typeof r['trace_path']!=='string'||r['trace_path']==='')return false;
 if(r['execution_mode']==='sequential'){
  if(r['concurrency_limit']!==1||r['peak_concurrency']!==1)return false;
 }else if(r['execution_mode']==='parallel'){
  if(r['concurrency_limit']!==2)return false;
 }else{return false;}
 if(!isIntAtLeast(r['peak_concurrency'],1)||(r['peak_concurrency'] as number)>2)return false;
 if(!validAttribution(r['attribution']))return false;
 return validStatusShape(r);
}
export function assembleResult(input:{run_id:string;trace_path:string;case:CaseForAssembly;peak_concurrency:1|2;outcomes:readonly WorkerOutcome[];brief:Brief|null;attribution:AttributionBlock}):RunResult{
 const canonical=canonicalizeOutcomes(input.outcomes,input.case.order_id);
 const successes=canonical.filter(o=>o.status==='SUCCEEDED').length;
 if((successes>0)!==(input.brief!==null))throw new Error('Brief presence must match successful evidence');
 const result:RunResult={
  schema_version:'1.0',run_id:input.run_id,scenario_id:'order-brief',case_id:input.case.case_id,
  execution_mode:input.case.execution_mode,concurrency_limit:input.case.limit,peak_concurrency:input.peak_concurrency,
  order_id:input.case.order_id,status:successes===3?'SUCCEEDED':successes>0?'PARTIAL':'FAILED',
  worker_outcomes:canonical,synthesis_invoked:successes>0,brief:input.brief,
  failure_code:successes>0?null:'ALL_WORKERS_FAILED',trace_path:input.trace_path,attribution:input.attribution};
 if(!validateResult(result))throw new Error('Invalid run result');
 return result;
}
