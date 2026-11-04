import {expect,test} from 'vitest';
import {validateWorkerOutput,validateRunResult,validateRunStateDocument,canonicalStateBody,stateDigest} from '../src/schemas.js';
import type {RunResult,RunStateDocument,WorkerOutcome} from '../src/types.js';
test('reject_original_invalid_output',()=>{
 const cycle:Record<string,unknown>={};cycle.self=cycle;
 const valid={order_id:'ORD-1001',payment_status:'PAID'};
 expect(validateWorkerOutput('payment-status',valid,'ORD-1001')).toEqual({valid:true,value:valid});
 for(const raw of [{...valid,private:'secret'},{...valid,order_id:'ORD-9999'},{...valid,payment_status:'UNKNOWN'},NaN,Infinity,cycle,{...valid,n:2**54}])
  expect(validateWorkerOutput('payment-status',raw,'ORD-1001')).toEqual({valid:false});
});
test('validate_run_state_document_enforces_closed_schema',()=>{
 const base={state_schema_version:'1.0',run_id:'r1',scenario_id:'order-brief-recovery',case_id:'c',execution_mode:'parallel',concurrency_limit:2,requested_order_id:'ORD-1001',status:'RUNNING',steps:[
  {worker_id:'order-details',status:'PENDING',output:null,failure_code:null},
  {worker_id:'payment-status',status:'PENDING',output:null,failure_code:null},
  {worker_id:'delivery-status',status:'PENDING',output:null,failure_code:null}],sequence_cursor:0};
 const body=canonicalStateBody(base as unknown as RunStateDocument);
 const doc={...base,digest:stateDigest(body)} as unknown as RunStateDocument;
 expect(validateRunStateDocument(doc).valid).toBe(true);
 expect(validateRunStateDocument({...doc,extra:1}).valid).toBe(false);
 expect(validateRunStateDocument({...doc,digest:'zz'}).valid).toBe(false);
 expect(validateRunStateDocument({...doc,steps:doc.steps.slice(0,2)}).valid).toBe(false);
});
test('validate_run_result_uses_recovery_schema_and_canonical_body_rules',()=>{
 const outputs=[{order_id:'ORD-1001',order_status:'SHIPPED'},{order_id:'ORD-1001',payment_status:'PAID'},{order_id:'ORD-1001',delivery_status:'DELIVERED'}] as const;
 const ids=['order-details','payment-status','delivery-status'] as const;
 const outcome=(i:number,failed=false):WorkerOutcome=>failed?{worker_id:ids[i]!,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'}:{worker_id:ids[i]!,status:'SUCCEEDED',output:outputs[i]!,failure_code:null};
 const attribution={steps:[{step_name:'worker.order-details',latency_ms:10,cost_cents:0,attempts:1},{step_name:'worker.payment-status',latency_ms:11,cost_cents:0,attempts:1},{step_name:'worker.delivery-status',latency_ms:12,cost_cents:0,attempts:1},{step_name:'synthesize',latency_ms:15,cost_cents:0,attempts:1}],totals:{latency_ms:48,cost_cents:0,attempts:4}};
 const result:RunResult={schema_version:'1.0',run_id:'r1',scenario_id:'order-brief-recovery',case_id:'c',execution_mode:'parallel',concurrency_limit:2,peak_concurrency:2,order_id:'ORD-1001',status:'SUCCEEDED',worker_outcomes:[outcome(0),outcome(1),outcome(2)],synthesis_invoked:true,brief:{order_id:'ORD-1001',sections:[{worker_id:'order-details',output:outputs[0]},{worker_id:'payment-status',output:outputs[1]},{worker_id:'delivery-status',output:outputs[2]}],missing_workers:[],complete:true},failure_code:null,trace_path:'t.jsonl',resumed:false,restored_cursor:null,restored_worker_ids:[],state_dir:'state',run_state_status:'SUCCEEDED',attribution};
 expect(validateRunResult(result)).toBe(true);
 expect(validateRunResult({...result,status:'CANCELLED',synthesis_invoked:false,brief:null,failure_code:'ALL_WORKERS_FAILED',run_state_status:'CANCELLED'})).toBe(false);
 expect(validateRunResult({...result,resumed:true})).toBe(false);
 expect(canonicalStateBody({...result,digest:'x'} as unknown as RunStateDocument)).toBe(canonicalStateBody(result as unknown as RunStateDocument));
 expect(stateDigest('{"a":1}')).toBe(stateDigest('{"a":1}'));
 expect(canonicalStateBody({digest:'ignored',b:2,a:1} as unknown as RunStateDocument)).toBe('{"a":1,"b":2}');
});

