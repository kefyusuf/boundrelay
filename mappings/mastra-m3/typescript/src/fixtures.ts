/** Strict fixture loading for the P5c mapping: checked-in artifacts only.
 *
 * Reads the canonical Go fixture projections
 * (fixtures/goprojections/order-brief/{scenario,workers,attribution}.json)
 * and the M3 goldens' result projections (fixtures/goldens/order-brief/).
 * No YAML, no network, no mutation of the sources.
 */
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {STEP_KINDS,type AttributionTables} from './attribution.js';
export {STEP_KINDS} from './attribution.js';

export const ROOT=fileURLToPath(new URL('../../../../',import.meta.url)).replace(/[/\\]$/,'');
const PROJECTION_DIR=ROOT+'/fixtures/goprojections/order-brief';
const GOLDEN_DIR=ROOT+'/fixtures/goldens/order-brief';
export const WORKER_IDS=['order-details','payment-status','delivery-status'] as const;
export type WorkerIdList=typeof WORKER_IDS;
export const PARITY_CASE_KEYS=[
 'sequential-complete','parallel-complete','parallel-out-of-order',
 'parallel-partial-failure','parallel-all-failed','parallel-invalid-output'] as const;
const ORD_PATTERN=/^ORD-[0-9]{4}$/;
export type WorkerInstruction={operation:'return';output:unknown}|{operation:'raise';failure_code:'WORKER_EXECUTION_FAILED'};
export type WorkerInstructions=Record<string,WorkerInstruction>;
export type CaseSpec={case_id:string;execution_mode:'sequential'|'parallel';worker_fixture:string;completion_order:string[]};
export type RunCase={case_id:string;execution_mode:'sequential'|'parallel';completion_order:readonly string[];instructions:WorkerInstructions;order_id:string;latency_ms:Record<string,number>;price_table:Record<string,number>;readonly limit:1|2};
export type Scenario={schema_version:'1.0';scenario_id:'order-brief';order_id:string;cases:CaseSpec[];attribution:AttributionTables};
export type GoldenProjection=Record<string,unknown>&{case_id:string;attribution:unknown};

function fields(raw:unknown,keys:readonly string[]):Record<string,unknown>{
 if(raw===null||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).sort().join('|')!==keys.toSorted().join('|'))throw new Error('Invalid fixture fields');
 return raw as Record<string,unknown>;
}
function loadJson(path:string):unknown{
 let text:string;
 try{text=readFileSync(path,'utf8');}catch(error){throw new Error(`Invalid fixture document: ${path}`);}
 try{return JSON.parse(text) as unknown;}catch{throw new Error(`Invalid fixture document: ${path}`);}
}
const isOrd=(value:unknown):boolean=>typeof value==='string'&&ORD_PATTERN.test(value);
function validLatency(raw:unknown):boolean{
 return typeof raw==='object'&&raw!==null&&!Array.isArray(raw)&&Object.keys(raw).length>0&&Object.entries(raw).every(([k,v])=>k!==''&&Number.isInteger(v)&&v>=0);
}
function validPriceTable(raw:unknown):boolean{
 return typeof raw==='object'&&raw!==null&&!Array.isArray(raw)&&Object.keys(raw).length>0&&Object.entries(raw).every(([k,v])=>(STEP_KINDS as readonly string[]).includes(k)&&Number.isInteger(v)&&v>=0)&&(!('read' in (raw as Record<string,unknown>))||(raw as Record<string,unknown>)['read']===0);
}
export function parseAttribution(raw:unknown):AttributionTables{
 const a=fields(raw,['latency_ms','price_table']);
 if(!validLatency(a['latency_ms']))throw new Error('Invalid attribution latency table');
 if(!validPriceTable(a['price_table']))throw new Error('Invalid attribution price table');
 return {latency_ms:{...(a['latency_ms'] as Record<string,number>)},price_table:{...(a['price_table'] as Record<string,number>)}};
}
function validInstruction(instruction:unknown):boolean{
 if(instruction===null||typeof instruction!=='object')return false;
 const i=instruction as Record<string,unknown>;
 if(i['operation']==='return'){
  fields(i,['operation','output']);
  const output=i['output'];
  // The output itself may be deliberately invalid (the invalid-output
  // case); only the envelope is validated here. Output shape is judged
  // inside the worker step (INVALID_WORKER_OUTPUT path).
  return typeof output==='object'&&output!==null&&'order_id' in output&&isOrd((output as Record<string,unknown>)['order_id']);
 }
 if(i['operation']==='raise'){
  fields(i,['operation','failure_code']);
  return i['failure_code']==='WORKER_EXECUTION_FAILED';
 }
 return false;
}
export function parseWorkers(raw:unknown,scenario:Scenario):Record<string,WorkerInstructions>{
 const refs=new Set(scenario.cases.map(c=>c.worker_fixture));
 if(raw===null||typeof raw!=='object'||Array.isArray(raw)){throw new Error('Workers projection must cover exactly the fixtures');}
 const record=raw as Record<string,unknown>;
 if(Object.keys(record).length!==refs.size||Object.keys(record).some(k=>!refs.has(k)))throw new Error('Workers projection must cover exactly the fixtures');
 for(const [ref,fixture] of Object.entries(record)){
  fields(fixture,WORKER_IDS);
  for(const instruction of Object.values(fixture as Record<string,unknown>)){
   if(!validInstruction(instruction))throw new Error(`Invalid worker instruction in ${ref}`);
  }
 }
 return record as Record<string,WorkerInstructions>;
}
function feasible(order:readonly string[],mode:'sequential'|'parallel'):boolean{
 const active=new Set<string>();const pending=[...WORKER_IDS];
 const limit=mode==='sequential'?1:2;
 for(const next of order){
  while(active.size<limit&&pending.length)active.add(pending.shift()!);
  if(!active.delete(next))return false;
 }
 return true;
}
function parseCase(raw:unknown,seen:Set<string>):CaseSpec{
 const c=fields(raw,['case_id','execution_mode','worker_fixture','completion_order']);
 const order=c['completion_order'];
 if(typeof c['case_id']!=='string'||c['case_id']===''||seen.has(c['case_id'])
  ||(c['execution_mode']!=='sequential'&&c['execution_mode']!=='parallel')
  ||!Array.isArray(order)||order.length!==3
  ||order.some(id=>!(WORKER_IDS as readonly string[]).includes(id))
  ||order.toSorted().join('|')!==WORKER_IDS.toSorted().join('|'))throw new Error('Invalid case specification');
 if(!feasible(order,c['execution_mode']))throw new Error('Infeasible completion schedule');
 seen.add(c['case_id'] as string);
 return {case_id:c['case_id'] as string,execution_mode:c['execution_mode'] as 'sequential'|'parallel',worker_fixture:c['worker_fixture'] as string,completion_order:[...(order as string[])]};
}
export function parseScenario(raw:unknown):Scenario{
 const s=fields(raw,['schema_version','scenario_id','order_id','cases','attribution']);
 if(s['schema_version']!=='1.0'||s['scenario_id']!=='order-brief'||!isOrd(s['order_id'])||!Array.isArray(s['cases'])||s['cases'].length!==6)throw new Error('Invalid scenario projection');
 const seen=new Set<string>();
 const cases=s['cases'].map(c=>parseCase(c,seen));
 return {schema_version:'1.0',scenario_id:'order-brief',order_id:s['order_id'] as string,cases,attribution:parseAttribution(s['attribution'])};
}
export function loadScenarioProjection():Scenario{return parseScenario(loadJson(PROJECTION_DIR+'/scenario.json'));}
export function loadWorkersProjection():Record<string,WorkerInstructions>{return parseWorkers(loadJson(PROJECTION_DIR+'/workers.json'),loadScenarioProjection());}
export function loadAttributionProjection():AttributionTables{return parseAttribution(loadJson(PROJECTION_DIR+'/attribution.json'));}
export function loadGolden(caseKey:string):GoldenProjection{
 if(!(PARITY_CASE_KEYS as readonly string[]).includes(caseKey))throw new Error(`Unknown parity case: ${caseKey}`);
 const golden=loadJson(`${GOLDEN_DIR}/${caseKey}.json`) as Record<string,unknown>;
 if(golden['case_key']!==caseKey||golden['result_projection']===undefined||typeof golden['result_projection']!=='object'||golden['result_projection']===null||!('attribution' in golden['result_projection']))throw new Error(`Invalid golden projection: ${caseKey}`);
 return golden['result_projection'] as GoldenProjection;
}
export function loadCase(caseId:string):RunCase{
 const scenario=loadScenarioProjection();
 const spec=scenario.cases.find(c=>c.case_id===caseId);
 if(spec===undefined)throw new Error(`Unknown case: ${caseId}`);
 const workers=loadWorkersProjection();
 const instructions=workers[spec.worker_fixture];
 if(instructions===undefined)throw new Error(`Missing worker fixture: ${spec.worker_fixture}`);
 return {case_id:spec.case_id,execution_mode:spec.execution_mode,completion_order:[...spec.completion_order],instructions,order_id:scenario.order_id,latency_ms:{...scenario.attribution.latency_ms},price_table:{...scenario.attribution.price_table},limit:spec.execution_mode==='sequential'?1:2};
}
export function loadScenario():Scenario{return loadScenarioProjection();}
