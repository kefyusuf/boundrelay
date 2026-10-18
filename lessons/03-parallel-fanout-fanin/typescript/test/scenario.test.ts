import {expect,test} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,symlinkSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {basename,join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {parse} from 'yaml';
import {ROOT,SCENARIO_PATH} from '../src/paths.js';
import {loadScenario,parseScenario,loadWorkerFixture} from '../src/scenario.js';
test('reject_infeasible_schedule',()=>{
 const raw=parse(readFileSync(SCENARIO_PATH,'utf8'));
 for(const order of [['payment-status','order-details','delivery-status'],['order-details','order-details','delivery-status'],['order-details','payment-status'],['unknown','payment-status','delivery-status']]){
  const bad=structuredClone(raw);bad.cases[0].completion_order=order;expect(()=>parseScenario(bad)).toThrow();
 }
 const bad=structuredClone(raw);bad.cases[1].completion_order=['delivery-status','order-details','payment-status'];expect(()=>parseScenario(bad)).toThrow();
 const duplicate=structuredClone(raw);duplicate.cases[1].case_id=duplicate.cases[0].case_id;expect(()=>parseScenario(duplicate)).toThrow();
});
test('invalid_return_reaches_runtime_validation',()=>{
 const scenario=loadScenario();expect(scenario.cases).toHaveLength(6);
 const c=scenario.cases.find(c=>c.case_id==='parallel-invalid-output')!;
 expect(loadWorkerFixture(c.worker_fixture)['payment-status']).toEqual({operation:'return',output:{order_id:'ORD-1001',payment_status:'UNKNOWN'}});
});

test('reject_fixture_symlink_escaping_worker_directory',()=>{
 const external=mkdtempSync(join(tmpdir(),'br-m3-fixture-'));
 const escaped=join(ROOT,'fixtures/workers/order-brief','m3-escape-'+randomUUID()+'.yaml');
 try {
  writeFileSync(join(external,'outside.yaml'),readFileSync(join(ROOT,'fixtures/workers/order-brief/complete.yaml')));
  try {symlinkSync(join(external,'outside.yaml'),escaped,'file');}
  catch(error) {
   if(process.platform==='win32' && (error as NodeJS.ErrnoException).code==='EPERM')return;
   throw error;
  }
  expect(()=>loadWorkerFixture('fixtures/workers/order-brief/'+basename(escaped))).toThrow('Worker fixture escapes root');
 } finally {rmSync(escaped,{force:true});rmSync(external,{recursive:true,force:true});}
});
