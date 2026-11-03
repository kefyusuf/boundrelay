import {readFileSync,realpathSync} from 'node:fs';
import {resolve,relative,isAbsolute} from 'node:path';
import {parse} from 'yaml';
import {ROOT,SCENARIO_PATH} from './paths.js';
import {WORKER_IDS,type CaseSpec,type RecoveryControls,type Scenario,type WorkerId,type WorkerInstructions} from './types.js';
const CASE_BASE=['case_id','execution_mode','worker_fixture','completion_order'],CASE_OPTIONAL=['controls','replay_from_step','tampered_state'];
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
function caseObject(raw:unknown):Record<string,unknown>{
 if(raw===null||typeof raw!=='object'||Array.isArray(raw))throw new Error('Invalid case fields');
 const keys=Object.keys(raw);
 if(!CASE_BASE.every(key=>keys.includes(key))||keys.some(key=>![...CASE_BASE,...CASE_OPTIONAL].includes(key)))throw new Error('Invalid case fields');
 return raw as Record<string,unknown>;
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
function parseControls(raw:unknown,completion:WorkerId[]):RecoveryControls {
 if(raw===null||typeof raw!=='object'||Array.isArray(raw))throw new Error('Invalid controls');
 const entries=Object.entries(raw);
 if(entries.length!==1)throw new Error('Invalid controls');
 const [key,value]=entries[0]!;
 if(key!=='crash_after'&&key!=='cancel_before')throw new Error('Unknown control field');
 if(typeof value!=='string'||!WORKER_IDS.includes(value as WorkerId))throw new Error('Invalid control target');
 const target=value as WorkerId;
 if(key==='crash_after'){
  const prefix=[...WORKER_IDS.slice(0,WORKER_IDS.indexOf(target)+1)],pos=(id:WorkerId)=>completion.indexOf(id);
  if(prefix.length<2||prefix.some(id=>id!==target&&pos(id)>pos(target)))throw new Error('Infeasible crash target');
  return {crash_after:target as WorkerId};
 }
 if(target!==WORKER_IDS[WORKER_IDS.length-1])throw new Error('Infeasible cancel target');
 return {cancel_before:target as WorkerId};
}
export function parseScenario(raw:unknown):Scenario {
 const hasAttribution=raw!==null&&typeof raw==='object'&&!Array.isArray(raw)&&Object.keys(raw).includes('attribution');
 const s=object(raw,['schema_version','scenario_id','order_id','cases',...(hasAttribution?['attribution']:[])]);
 parseAttribution(s.attribution);
 if(s.schema_version!=='1.0'||s.scenario_id!=='order-brief-recovery'||typeof s.order_id!=='string'||!/^ORD-[0-9]{4}$/.test(s.order_id)||!Array.isArray(s.cases)||s.cases.length!==6)throw new Error('Invalid scenario');
 const seen=new Set<string>();const cases:CaseSpec[]=[];
 for(const rawCase of s.cases){
  const c=caseObject(rawCase),keys=Object.keys(c);
  if(typeof c.case_id!=='string'||!c.case_id||seen.has(c.case_id)||!['sequential','parallel'].includes(String(c.execution_mode))||typeof c.worker_fixture!=='string')throw new Error('Invalid case');
  seen.add(c.case_id);loadWorkerFixture(c.worker_fixture);
  const order=c.completion_order;
  if(!Array.isArray(order)||order.length!==3||order.toSorted().join('|')!==[...WORKER_IDS].sort().join('|'))throw new Error('Invalid completion permutation');
  const completion=order as WorkerId[];
  if(CASE_OPTIONAL.filter(key=>keys.includes(key)).length>1)throw new Error('Invalid control combination');
  const controls=keys.includes('controls')?parseControls(c.controls,completion):undefined;
  let replayFromStep:number|undefined;
  if(keys.includes('replay_from_step')){const v=c.replay_from_step;if(typeof v!=='number'||!Number.isInteger(v)||v<1||v>3)throw new Error('Invalid replay_from_step');replayFromStep=v;}
  let tamperedState:string|undefined;
  if(keys.includes('tampered_state')){if(c.tampered_state!=='flip_payment_outcome')throw new Error('Invalid tampered_state');tamperedState=c.tampered_state;}
  const spec:CaseSpec={case_id:c.case_id,execution_mode:c.execution_mode as CaseSpec['execution_mode'],worker_fixture:c.worker_fixture,completion_order:completion};
  if(controls)spec.controls=controls;
  if(replayFromStep!==undefined)spec.replay_from_step=replayFromStep;
  if(tamperedState!==undefined)spec.tampered_state=tamperedState;
  cases.push(spec);
  const active=new Set<WorkerId>(),pending=[...WORKER_IDS];const limit=c.execution_mode==='sequential'?1:2;
  for(const next of completion){while(active.size<limit&&pending.length)active.add(pending.shift()!);if(!active.delete(next))throw new Error('Infeasible completion schedule');}
 }
 return {schema_version:'1.0',scenario_id:'order-brief-recovery',order_id:s.order_id,cases};
}
export function loadScenario():Scenario {return parseScenario(parse(readFileSync(SCENARIO_PATH,'utf8')));}

