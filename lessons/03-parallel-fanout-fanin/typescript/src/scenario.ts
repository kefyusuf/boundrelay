import {readFileSync,realpathSync} from 'node:fs';
import {resolve,relative,isAbsolute} from 'node:path';
import {parse} from 'yaml';
import {ROOT,SCENARIO_PATH} from './paths.js';
import {WORKER_IDS,type WorkerId,type Scenario,type WorkerInstructions} from './types.js';
function object(raw:unknown,keys:string[]):Record<string,unknown>{
 if(raw===null||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).sort().join('|')!==keys.toSorted().join('|'))throw new Error('Invalid fixture fields');
 return raw as Record<string,unknown>;
}
const STEP_KINDS=['read','model_decision','tool_call','effect','handoff','route','synthesis'];
function parseAttribution(raw:unknown):void{
 if(raw===null||raw===undefined)return;
 const a=object(raw,['latency_ms','price_table']),latency=a.latency_ms,prices=a.price_table;
 const ints=(v:unknown)=>typeof v==='number'&&Number.isInteger(v)&&v>=0;
 if(latency===null||typeof latency!=='object'||Array.isArray(latency)||Object.keys(latency).length===0||Object.entries(latency).some(([k,v])=>!k||!ints(v)))throw new Error('Invalid scenario');
 if(prices===null||typeof prices!=='object'||Array.isArray(prices)||Object.keys(prices).length===0||Object.entries(prices).some(([k,v])=>!STEP_KINDS.includes(k)||!ints(v)))throw new Error('Invalid scenario');
 if((prices as Record<string,unknown>).read!==0)throw new Error('Invalid scenario');
}
export function loadWorkerFixture(path:string):WorkerInstructions {
 const base=realpathSync(resolve(ROOT,'fixtures/workers/order-brief')),target=realpathSync(resolve(ROOT,path)),rel=relative(base,target);
 if(rel.startsWith('..')||isAbsolute(rel))throw new Error('Worker fixture escapes root');
 const raw=object(parse(readFileSync(target,'utf8')),[...WORKER_IDS]);
 for(const id of WORKER_IDS){const v=raw[id] as Record<string,unknown>;
  if(v?.operation==='return')object(v,['operation','output']);
  else if(v?.operation==='raise'&&v.failure_code==='WORKER_EXECUTION_FAILED')object(v,['operation','failure_code']);
  else throw new Error('Invalid worker operator');
 }
 return raw as unknown as WorkerInstructions;
}
export function parseScenario(raw:unknown):Scenario {
 const hasAttribution=raw!==null&&typeof raw==='object'&&!Array.isArray(raw)&&Object.keys(raw).includes('attribution');
 const s=object(raw,['schema_version','scenario_id','order_id','cases',...(hasAttribution?['attribution']:[])]);
 parseAttribution(s.attribution);
 if(s.schema_version!=='1.0'||s.scenario_id!=='order-brief'||typeof s.order_id!=='string'||!/^ORD-[0-9]{4}$/.test(s.order_id)||!Array.isArray(s.cases)||s.cases.length!==6)throw new Error('Invalid scenario');
 const seen=new Set<string>();
 for(const rawCase of s.cases){const c=object(rawCase,['case_id','execution_mode','worker_fixture','completion_order']);
  if(typeof c.case_id!=='string'||!c.case_id||seen.has(c.case_id)||!['sequential','parallel'].includes(String(c.execution_mode))||typeof c.worker_fixture!=='string')throw new Error('Invalid case');
  seen.add(c.case_id);loadWorkerFixture(c.worker_fixture);
  if(!Array.isArray(c.completion_order)||c.completion_order.length!==3||c.completion_order.toSorted().join('|')!==[...WORKER_IDS].sort().join('|'))throw new Error('Invalid completion permutation');
  const active=new Set<WorkerId>(),pending=[...WORKER_IDS];const limit=c.execution_mode==='sequential'?1:2;
  for(const next of c.completion_order){while(active.size<limit&&pending.length)active.add(pending.shift()!);if(!active.delete(next))throw new Error('Infeasible completion schedule');}
 }
 const {attribution:unused,...scenario}=s;void unused;
 return structuredClone(scenario) as unknown as Scenario;
}
export function loadScenario():Scenario {return parseScenario(parse(readFileSync(SCENARIO_PATH,'utf8')));}
