import {expect,test} from 'vitest';
import {validateWorkerOutput,validateRunResult,validateRunStateDocument,validateEffectPayload,validateEffectRecord,validateAuditRecord,canonicalStateBody,stateDigest} from '../src/schemas.js';
import type {RunResult,RunStateDocument,WorkerOutcome} from '../src/types.js';
const IDS=['order-details','payment-status','delivery-status'] as const;
const OUTPUTS=[{order_id:'ORD-1001',order_status:'SHIPPED'},{order_id:'ORD-1001',payment_status:'PAID'},{order_id:'ORD-1001',delivery_status:'DELAYED'}] as const;
const outcome=(i:number,failed=false):WorkerOutcome=>failed?{worker_id:IDS[i]!,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'}:{worker_id:IDS[i]!,status:'SUCCEEDED',output:OUTPUTS[i]!,failure_code:null};
test('reject_original_invalid_output',()=>{
 const cycle:Record<string,unknown>={};cycle.self=cycle;
 const valid={order_id:'ORD-1001',payment_status:'PAID'};
 expect(validateWorkerOutput('payment-status',valid,'ORD-1001')).toEqual({valid:true,value:valid});
 for(const raw of [{...valid,private:'secret'},{...valid,order_id:'ORD-9999'},{...valid,payment_status:'UNKNOWN'},NaN,Infinity,cycle,{...valid,n:2**54}])
  expect(validateWorkerOutput('payment-status',raw,'ORD-1001')).toEqual({valid:false});
});
const BASE={state_schema_version:'1.0',run_id:'r1',scenario_id:'order-closure',case_id:'c',execution_mode:'parallel',concurrency_limit:2,requested_order_id:'ORD-1001',status:'RUNNING',steps:[
 {worker_id:'order-details',status:'PENDING',output:null,failure_code:null},
 {worker_id:'payment-status',status:'PENDING',output:null,failure_code:null},
 {worker_id:'delivery-status',status:'PENDING',output:null,failure_code:null}],sequence_cursor:0};
test('validate_run_state_document_enforces_closed_m5_schema',()=>{
 const body=canonicalStateBody(BASE as unknown as RunStateDocument);
 const doc={...BASE,digest:stateDigest(body)} as unknown as RunStateDocument;
 expect(validateRunStateDocument(doc).valid).toBe(true);
 expect(validateRunStateDocument({...doc,extra:1}).valid).toBe(false);
 expect(validateRunStateDocument({...doc,digest:'zz'}).valid).toBe(false);
 expect(validateRunStateDocument({...doc,steps:doc.steps.slice(0,2)}).valid).toBe(false);
 expect(validateRunStateDocument({...doc,scenario_id:'order-brief-recovery'}).valid).toBe(false);
 const unknown={...doc,status:'UNKNOWN'} as RunStateDocument;
 expect(validateRunStateDocument(unknown).valid).toBe(true);
});
test('validate_run_result_uses_m5_schema_with_effect_fields',()=>{
 const result:RunResult={schema_version:'1.0',run_id:'r1',scenario_id:'order-closure',case_id:'c',execution_mode:'parallel',concurrency_limit:2,peak_concurrency:2,order_id:'ORD-1001',status:'SUCCEEDED',worker_outcomes:[outcome(0),outcome(1),outcome(2)],synthesis_invoked:false,brief:null,failure_code:null,approval_decision:'granted',effect_status:'EFFECT_COMPLETED',idempotency_key:'cancel-and-refund:ORD-1001',reconciled:false,trace_path:'t.jsonl',resumed:false,restored_cursor:null,restored_worker_ids:[],state_dir:'state',run_state_status:'SUCCEEDED'};
 expect(validateRunResult(result)).toBe(true);
 expect(validateRunResult({...result,reconciled:true})).toBe(true);
 expect(validateRunResult({...result,status:'UNKNOWN',failure_code:null,approval_decision:'granted',effect_status:'EFFECT_UNPROVABLE',reconciled:false,run_state_status:'UNKNOWN'})).toBe(true);
 expect(validateRunResult({...result,status:'UNKNOWN',effect_status:'EFFECT_COMPLETED',run_state_status:'UNKNOWN'})).toBe(false);
 expect(validateRunResult({...result,status:'UNKNOWN',failure_code:'ALL_WORKERS_FAILED',effect_status:'EFFECT_UNPROVABLE',run_state_status:'UNKNOWN'})).toBe(false);
 expect(validateRunResult({...result,status:'PARTIAL',reconciled:true,approval_decision:'none',effect_status:null,idempotency:null,run_state_status:'PARTIAL'} as unknown as RunResult)).toBe(false);
 expect(validateRunResult({...result,extra:1})).toBe(false);
 expect(validateRunResult({...result,synthesis_invoked:true})).toBe(false);
});
const PAYLOAD={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'};
const DIGEST='c'.repeat(64);
test('effect_payload_and_ledger_records_validate_against_closed_schema',()=>{
 expect(validateEffectPayload(PAYLOAD).valid).toBe(true);
 expect(validateEffectPayload({...PAYLOAD,refund_amount_cents:4300}).valid).toBe(false);
 expect(validateEffectPayload({...PAYLOAD,memo:'x'}).valid).toBe(false);
 const completed={status:'EFFECT_COMPLETED',outcome:{refund_id:'RFL-1001',refunded_at:'2026-11-02T00:00:00Z'}};
 const record={key:'cancel-and-refund:ORD-1001',payload_digest:DIGEST,effect:completed};
 expect(validateEffectRecord(record).valid).toBe(true);
 expect(validateEffectRecord({...record,payload_digest:'C'.repeat(64)}).valid).toBe(false);
 expect(validateEffectRecord({...record,extra:1}).valid).toBe(false);
 expect(validateEffectRecord({key:'k',payload_digest:DIGEST}).valid).toBe(false);
});
test('audit_records_validate_against_the_closed_oneof_schema',()=>{
 const approval={kind:'approval',operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:DIGEST,decision:'granted',approver:'approver-primary'};
 const effect={kind:'effect',operation:'cancel-and-refund',order_id:'ORD-1001',idempotency_key:'cancel-and-refund:ORD-1001',effect_status:'EFFECT_COMPLETED',duplicate:false};
 expect(validateAuditRecord(approval)).toBe(true);
 expect(validateAuditRecord(effect)).toBe(true);
 expect(validateAuditRecord({...approval,idempotency_key:'x'})).toBe(false);
 expect(validateAuditRecord({...effect,payload_digest:DIGEST})).toBe(false);
 expect(validateAuditRecord({...approval,decision:'approved'})).toBe(false);
});
test('canonical_body_and_digest_rules_unchanged_from_m4',()=>{
 expect(canonicalStateBody({digest:'ignored',b:2,a:1} as unknown as RunStateDocument)).toBe('{"a":1,"b":2}');
 expect(stateDigest('{"a":1}')).toBe(stateDigest('{"a":1}'));
});


