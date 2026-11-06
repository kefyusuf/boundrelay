import {describe,expect,test} from 'vitest';
import {loadCase,loadGolden,loadScenarioProjection,loadWorkersProjection,parseScenario,PARITY_CASE_KEYS,WORKER_IDS,STEP_KINDS} from '../src/fixtures.js';

const deepCopy=(v:unknown):unknown=>structuredClone(v);

describe('strict fixture projection loading',()=>{
 test('scenario projection has the six canonical cases and attribution tables',()=>{
  const scenario=loadScenarioProjection();
  expect(scenario.schema_version).toBe('1.0');
  expect(scenario.scenario_id).toBe('order-brief');
  expect(scenario.order_id).toBe('ORD-1001');
  expect(scenario.cases.map(c=>c.case_id)).toEqual([...PARITY_CASE_KEYS]);
  expect(Object.keys(scenario.attribution.latency_ms).sort()).toEqual(['synthesize','worker.delivery-status','worker.order-details','worker.payment-status']);
  expect(scenario.attribution.price_table).toEqual({read:0,synthesis:0});
 });
 test('workers projection covers exactly the referenced fixtures',()=>{
  const scenario=loadScenarioProjection(),workers=loadWorkersProjection();
  const refs=[...new Set(scenario.cases.map(c=>c.worker_fixture))].sort();
  expect(Object.keys(workers).sort()).toEqual(refs);
  for(const fixture of Object.values(workers))expect(Object.keys(fixture)).toEqual([...WORKER_IDS]);
 });
 test('load_case assembles one case with its instructions and tables',()=>{
  const c=loadCase('parallel-complete');
  expect(c.case_id).toBe('parallel-complete');
  expect(c.execution_mode).toBe('parallel');
  expect(c.limit).toBe(2);
  expect(c.order_id).toBe('ORD-1001');
  expect(c.instructions['payment-status']).toEqual({operation:'return',output:{order_id:'ORD-1001',payment_status:'PAID'}});
  expect(loadCase('sequential-complete').limit).toBe(1);
 });
 test('unknown case raises',()=>{expect(()=>loadCase('no-such-case')).toThrow(/Unknown case/);});
 test('every parity case has a golden projection with attribution',()=>{
  for(const key of PARITY_CASE_KEYS){
   const golden=loadGolden(key);
   expect(golden.case_id).toBe(key);
   expect((golden.attribution as {steps:unknown[]}).steps.length).toBeGreaterThanOrEqual(3);
  }
  expect(()=>loadGolden('not-a-case')).toThrow(/Unknown parity case/);
 });
 test('tampered scenario projections are rejected',()=>{
  const base=deepCopy(JSON.parse(JSON.stringify(loadScenarioProjection()))) as Record<string,unknown>;
  const mutate=(fn:(s:Record<string,unknown>)=>void):unknown=>{const copy=deepCopy(base) as Record<string,unknown>;fn(copy);return copy;};
  expect(()=>parseScenario(mutate(s=>{s['schema_version']='2.0';}))).toThrow();
  expect(()=>parseScenario(mutate(s=>{s['scenario_id']='other';}))).toThrow();
  expect(()=>parseScenario(mutate(s=>{s['order_id']='ORD-12';}))).toThrow();
  expect(()=>parseScenario(mutate(s=>{s['cases']=(s['cases'] as unknown[]).slice(0,5);}))).toThrow();
  expect(()=>parseScenario(mutate(s=>{delete (s as Record<string,unknown>)['attribution'];}))).toThrow();
  expect(()=>parseScenario(mutate(s=>{(s['cases'] as Record<string,unknown>[])[0]!['completion_order']=['order-details','order-details','delivery-status'];}))).toThrow();
  expect(()=>parseScenario(mutate(s=>{(s['cases'] as Record<string,unknown>[])[0]!['completion_order']=['delivery-status','order-details','payment-status'];}))).toThrow(/Infeasible/);
 });
 test('step kinds cover the closed attribution vocabulary',()=>{
  expect([...STEP_KINDS]).toEqual(['read','model_decision','tool_call','effect','handoff','route','synthesis']);
 });
});
