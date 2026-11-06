import {describe,expect,test} from 'vitest';
import {assembleResult,canonicalizeOutcomes,finiteJson,synthesizeBrief,validateResult,validateWorkerOutput,validateWorkerOutcome,type WorkerId,type WorkerOutcome,type WorkerOutput} from '../src/results.js';
import {loadCase,loadGolden,WORKER_IDS} from '../src/fixtures.js';
import {buildAttribution} from '../src/attribution.js';

const succeeded=(worker_id:string,output:Record<string,unknown>):WorkerOutcome=>({worker_id:worker_id as WorkerId,status:'SUCCEEDED',output:output as WorkerOutput,failure_code:null});
const failedWith=(worker_id:string,code:'WORKER_EXECUTION_FAILED'|'INVALID_WORKER_OUTPUT'):WorkerOutcome=>({worker_id:worker_id as WorkerId,status:'FAILED',output:null,failure_code:code});
const failedUnknownCode=(worker_id:string):unknown=>({worker_id,status:'FAILED',output:null,failure_code:'MYSTERY_CODE'});
const completeOutcomes=():WorkerOutcome[]=>[
 succeeded('order-details',{order_id:'ORD-1001',order_status:'SHIPPED'}),
 succeeded('payment-status',{order_id:'ORD-1001',payment_status:'PAID'}),
 succeeded('delivery-status',{order_id:'ORD-1001',delivery_status:'DELAYED'})];

describe('worker output validation (before publication)',()=>{
 test('accepts the three worker output shapes',()=>{
  expect(validateWorkerOutput('order-details',{order_id:'ORD-1001',order_status:'SHIPPED'},'ORD-1001').valid).toBe(true);
  expect(validateWorkerOutput('payment-status',{order_id:'ORD-1001',payment_status:'UNPAID'},'ORD-1001').valid).toBe(true);
  expect(validateWorkerOutput('delivery-status',{order_id:'ORD-1001',delivery_status:'PENDING'},'ORD-1001').valid).toBe(true);
 });
 test('rejects wrong worker/field pairing, wrong order, extra fields, non-finite',()=>{
  expect(validateWorkerOutput('payment-status',{order_id:'ORD-1001',order_status:'SHIPPED'},'ORD-1001').valid).toBe(false);
  expect(validateWorkerOutput('payment-status',{order_id:'ORD-1001',payment_status:'UNKNOWN'},'ORD-1001').valid).toBe(false);
  expect(validateWorkerOutput('order-details',{order_id:'ORD-9999',order_status:'SHIPPED'},'ORD-1001').valid).toBe(false);
  expect(validateWorkerOutput('order-details',{order_id:'ORD-1001',order_status:'SHIPPED',extra:1},'ORD-1001').valid).toBe(false);
  expect(validateWorkerOutput('order-details',null,'ORD-1001').valid).toBe(false);
 });
 test('finiteJson guard blocks NaN, cycles and class instances',()=>{
  expect(finiteJson({ok:1})).toBe(true);
  expect(finiteJson({bad:Number.NaN})).toBe(false);
  const cyclic:{[k:string]:unknown}={};cyclic['self']=cyclic;
  expect(finiteJson(cyclic)).toBe(false);
  expect(finiteJson(new Date())).toBe(false);
 });
});

describe('canonical fan-in',()=>{
 test('canonicalizes into WORKER_IDS order regardless of arrival',()=>{
  const canonical=canonicalizeOutcomes([completeOutcomes()[2],completeOutcomes()[0],completeOutcomes()[1]],'ORD-1001');
  expect(canonical.map(o=>o.worker_id)).toEqual([...WORKER_IDS]);
 });
 test('rejects incomplete, duplicate or invalid fan-ins',()=>{
  expect(()=>canonicalizeOutcomes(completeOutcomes().slice(0,2),'ORD-1001')).toThrow(/fan in/);
  expect(()=>canonicalizeOutcomes([completeOutcomes()[0],completeOutcomes()[0],completeOutcomes()[2]],'ORD-1001')).toThrow(/Duplicate/);
  expect(()=>canonicalizeOutcomes([{...completeOutcomes()[0],failure_code:'BOGUS'} as unknown as WorkerOutcome,completeOutcomes()[1],completeOutcomes()[2]],'ORD-1001')).toThrow(/fan in/);
 });
 test('worker outcome shape validation',()=>{
  expect(validateWorkerOutcome(succeeded('order-details',{order_id:'ORD-1001',order_status:'SHIPPED'}),'ORD-1001')).toBe(true);
  expect(validateWorkerOutcome(failedWith('payment-status','INVALID_WORKER_OUTPUT'),'ORD-1001')).toBe(true);
  expect(validateWorkerOutcome(failedUnknownCode('payment-status'),'ORD-1001')).toBe(false);
 });
});

describe('synthesis (single deterministic brief)',()=>{
 test('sections in canonical order, missing from failures',()=>{
  const outcomes=[completeOutcomes()[0],failedWith('payment-status','WORKER_EXECUTION_FAILED'),completeOutcomes()[2]] as const;
  const brief=synthesizeBrief('ORD-1001',canonicalizeOutcomes([...outcomes],'ORD-1001'));
  expect(brief.sections.map(s=>s.worker_id)).toEqual(['order-details','delivery-status']);
  expect(brief.missing_workers).toEqual(['payment-status']);
  expect(brief.complete).toBe(false);
 });
 test('cannot synthesize without successful evidence',()=>{
  const all=canonicalizeOutcomes([failedWith('order-details','WORKER_EXECUTION_FAILED'),failedWith('payment-status','WORKER_EXECUTION_FAILED'),failedWith('delivery-status','WORKER_EXECUTION_FAILED')],'ORD-1001');
  expect(()=>synthesizeBrief('ORD-1001',all)).toThrow(/without successful evidence/);
 });
});

describe('result assembly + structural validation',()=>{
 test('assembles a schema-shaped SUCCEEDED result',()=>{
  const c=loadCase('parallel-complete');
  const canonical=canonicalizeOutcomes(completeOutcomes(),'ORD-1001');
  const brief=synthesizeBrief(c.order_id,canonical);
  const attribution=buildAttribution([...WORKER_IDS.map(id=>[`worker.${id}`,1] as const),['synthesize',1] as const],{latency_ms:c.latency_ms,price_table:c.price_table});
  const result=assembleResult({run_id:'r1',trace_path:'t.jsonl',case:c,peak_concurrency:2,outcomes:canonical,brief,attribution});
  expect(result.status).toBe('SUCCEEDED');
  expect(result.synthesis_invoked).toBe(true);
  expect(result.failure_code).toBeNull();
  expect(validateResult(result)).toBe(true);
 });
 test('validate_result mirrors the closed schema conditionals',()=>{
  const c=loadCase('parallel-complete');
  const canonical=canonicalizeOutcomes(completeOutcomes(),'ORD-1001');
  const base=assembleResult({run_id:'r',trace_path:'t',case:c,peak_concurrency:2,outcomes:canonical,brief:synthesizeBrief(c.order_id,canonical),attribution:buildAttribution([['synthesize',1]],{latency_ms:c.latency_ms,price_table:c.price_table})});
  expect(validateResult(base)).toBe(true);
  const brokenPeak={...base,peak_concurrency:3} as unknown as typeof base;
  expect(validateResult(brokenPeak)).toBe(false);
  const publishedUnknown={...base,worker_outcomes:[{...base.worker_outcomes[0],output:{order_id:'ORD-1001',order_status:'MYSTERY'}} as unknown as WorkerOutcome,...base.worker_outcomes.slice(1)] as unknown as typeof base.worker_outcomes} as typeof base;
  expect(validateResult(publishedUnknown)).toBe(false);
  const failedWithoutCode={...base,status:'FAILED' as const,synthesis_invoked:false,failure_code:null,brief:null} as typeof base;
  expect(validateResult(failedWithoutCode)).toBe(false);
  const badTotals={...base,attribution:{...base.attribution,totals:{...base.attribution.totals,attempts:99}}} as typeof base;
  expect(validateResult(badTotals)).toBe(false);
 });
 test('golden projections satisfy the structural validator',()=>{
  for(const key of ['sequential-complete','parallel-complete','parallel-out-of-order','parallel-partial-failure','parallel-all-failed','parallel-invalid-output']){
   const golden=loadGolden(key) as Record<string,unknown>;
   expect(validateResult({...golden,run_id:'r',trace_path:'t'}),key).toBe(true);
  }
 });
});
