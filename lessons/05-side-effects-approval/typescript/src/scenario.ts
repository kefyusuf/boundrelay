import {readFileSync,realpathSync} from 'node:fs';
import {resolve,relative,isAbsolute} from 'node:path';
import {parse} from 'yaml';
import {ROOT,SCENARIO_PATH} from './paths.js';
import {WORKER_IDS,type ApprovalMetadata,type CaseSpec,type RecoveryControls,type Scenario,type WorkerId,type WorkerInstructions} from './types.js';
const CASE_BASE=['case_id','execution_mode','worker_fixture','completion_order'],CASE_OPTIONAL=['approval','controls','duplicate_key'];
const APPROVAL_DECISIONS=new Set(['granted','rejected']);
const CONTROL_FIELDS=new Set(['crash_before_submit','crash_in_submit_window','sink_unavailable']);
const CANONICAL_CONTROLS:Record<string,string[]>={'approval-granted-effect-once':[],'approval-rejected-no-effect':[],'retry-before-submit':['crash_before_submit'],'crash-submit-window-resolved':['crash_in_submit_window'],'sink-unavailable-unknown':['crash_in_submit_window','sink_unavailable'],'duplicate-key-suppressed':[]};
function object(raw:unknown,keys:string[]):Record<string,unknown>{
 if(raw===null||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).sort().join('|')!==keys.toSorted().join('|'))throw new Error('Invalid fixture fields');
 return raw as Record<string,unknown>;
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
function parseApproval(raw:unknown):ApprovalMetadata {
 if(raw===null||typeof raw!=='object'||Array.isArray(raw))throw new Error('Invalid approval block');
 const record=raw as Record<string,unknown>;
 if(Object.keys(record).sort().join('|')!=='approver|decision')throw new Error('Invalid approval block');
 if(typeof record.decision!=='string'||!APPROVAL_DECISIONS.has(record.decision))throw new Error('Invalid approval decision');
 if(typeof record.approver!=='string'||!record.approver)throw new Error('Invalid approver');
 return {decision:record.decision as ApprovalMetadata['decision'],approver:record.approver};
}
export function parseControls(raw:unknown,caseId:string):RecoveryControls {
 if(raw===null||typeof raw!=='object'||Array.isArray(raw))throw new Error('Invalid controls');
 const record=raw as Record<string,unknown>;
 const fields=Object.keys(record).sort();
 if(fields.length===0)throw new Error('Invalid controls');
 for(const field of fields)if(!CONTROL_FIELDS.has(field))throw new Error('Unknown control field');
 for(const field of fields)if(record[field]!==true)throw new Error('Invalid control value');
 if(fields.includes('crash_before_submit')&&fields.length>1)throw new Error('Invalid control combination');
 if(fields.includes('sink_unavailable')&&(!fields.includes('crash_in_submit_window')||caseId!=='sink-unavailable-unknown'))throw new Error('Invalid control combination');
 const allowed=CANONICAL_CONTROLS[caseId];
 if(allowed===undefined||fields.join('|')!==[...allowed].sort().join('|'))throw new Error(`Invalid controls for case ${caseId}`);
 return record as RecoveryControls;
}
export function parseScenario(raw:unknown):Scenario {
 const s=object(raw,['schema_version','scenario_id','order_id','cases']);
 if(s.schema_version!=='1.0'||s.scenario_id!=='order-closure'||typeof s.order_id!=='string'||!/^ORD-[0-9]{4}$/.test(s.order_id)||!Array.isArray(s.cases)||s.cases.length!==6)throw new Error('Invalid scenario');
 const seen=new Set<string>();const cases:CaseSpec[]=[];
 for(const rawCase of s.cases){
  const c=caseObject(rawCase),keys=Object.keys(c);
  if(typeof c.case_id!=='string'||!c.case_id||seen.has(c.case_id)||!['sequential','parallel'].includes(String(c.execution_mode))||typeof c.worker_fixture!=='string')throw new Error('Invalid case');
  seen.add(c.case_id);loadWorkerFixture(c.worker_fixture);
  if(!keys.includes('approval'))throw new Error('Invalid case fields');
  const approval=parseApproval(c.approval);
  const order=c.completion_order;
  if(!Array.isArray(order)||order.length!==3||order.toSorted().join('|')!==[...WORKER_IDS].sort().join('|'))throw new Error('Invalid completion permutation');
  const completion=order as WorkerId[];
  const controls=keys.includes('controls')?parseControls(c.controls,c.case_id):undefined;
  if(keys.includes('duplicate_key')&&(c.case_id!=='duplicate-key-suppressed'||c.duplicate_key!==true))throw new Error('Invalid duplicate_key');
  const spec:CaseSpec={case_id:c.case_id,execution_mode:c.execution_mode as CaseSpec['execution_mode'],worker_fixture:c.worker_fixture,completion_order:completion,approval};
  if(controls)spec.controls=controls;
  if(keys.includes('duplicate_key'))spec.duplicate_key=true;
  cases.push(spec);
  const active=new Set<WorkerId>(),pending=[...WORKER_IDS];const limit=c.execution_mode==='sequential'?1:2;
  for(const next of completion){while(active.size<limit&&pending.length)active.add(pending.shift()!);if(!active.delete(next))throw new Error('Infeasible completion schedule');}
 }
 return {schema_version:'1.0',scenario_id:'order-closure',order_id:s.order_id,cases};
}
export function loadScenario():Scenario {return parseScenario(parse(readFileSync(SCENARIO_PATH,'utf8')));}



