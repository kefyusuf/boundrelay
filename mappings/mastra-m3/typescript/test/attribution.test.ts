import {describe,expect,test} from 'vitest';
import {buildAttribution,stepKind} from '../src/attribution.js';
import {loadAttributionProjection,loadCase} from '../src/fixtures.js';

const tables=()=>loadAttributionProjection();
const priced=(records:ReadonlyArray<readonly [string,number]>)=>buildAttribution(records,tables());

describe('attribution (M6 rules on the fixture tables)',()=>{
 test('latency is table x attempts and totals are the sum of steps',()=>{
  const a=priced([['worker.order-details',1],['worker.payment-status',2],['synthesize',1]]);
  expect(a.steps).toEqual([
   {step_name:'worker.order-details',latency_ms:10,cost_cents:0,attempts:1},
   {step_name:'worker.payment-status',latency_ms:22,cost_cents:0,attempts:2},
   {step_name:'synthesize',latency_ms:15,cost_cents:0,attempts:1}]);
  expect(a.totals).toEqual({latency_ms:47,cost_cents:0,attempts:4});
 });
 test('golden totals reproduce: 48/33 with synthesize, 33 without',()=>{
  const withSynth=priced([['worker.order-details',1],['worker.payment-status',1],['worker.delivery-status',1],['synthesize',1]]);
  expect(withSynth.totals).toEqual({latency_ms:48,cost_cents:0,attempts:4});
  const withoutSynth=priced([['worker.order-details',1],['worker.payment-status',1],['worker.delivery-status',1]]);
  expect(withoutSynth.totals).toEqual({latency_ms:33,cost_cents:0,attempts:3});
 });
 test('worker steps price as read kind; synthesize as synthesis',()=>{
  expect(stepKind('worker.payment-status')).toBe('read');
  expect(stepKind('synthesize')).toBe('synthesis');
  expect(()=>stepKind('mystery')).toThrow(/Unknown attribution step/);
 });
 test('rejects unknown steps, bad attempts, empty records',()=>{
  expect(()=>priced([['nope',1]])).toThrow(/Unknown attribution step/);
  expect(()=>priced([['synthesize',0]])).toThrow(/Invalid attribution attempts/);
  expect(()=>priced([['synthesize',1.5]])).toThrow(/Invalid attribution attempts/);
  expect(()=>priced([])).toThrow(/at least one executed step/);
 });
 test('projection tables match the tables carried by the cases',()=>{
  const c=loadCase('parallel-complete');
  expect(tables()).toEqual({latency_ms:c.latency_ms,price_table:c.price_table});
 });
});
