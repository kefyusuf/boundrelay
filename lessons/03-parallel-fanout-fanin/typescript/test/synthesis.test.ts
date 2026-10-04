import {expect,test} from 'vitest';
import {canonicalizeOutcomes} from '../src/collector.js';
import {synthesizeBrief} from '../src/synthesizer.js';
import {WORKER_IDS,type WorkerOutcome,type CanonicalOutcomes} from '../src/types.js';
const outcomes:CanonicalOutcomes=[
 {worker_id:'order-details',status:'SUCCEEDED',output:{order_id:'ORD-1001',order_status:'SHIPPED'},failure_code:null},
 {worker_id:'payment-status',status:'SUCCEEDED',output:{order_id:'ORD-1001',payment_status:'PAID'},failure_code:null},
 {worker_id:'delivery-status',status:'SUCCEEDED',output:{order_id:'ORD-1001',delivery_status:'DELAYED'},failure_code:null},
];
const fail=(i:number):WorkerOutcome=>({worker_id:WORKER_IDS[i]!,status:'FAILED',output:null,failure_code:'WORKER_EXECUTION_FAILED'});
test('canonical_merge_ignores_completion_order',()=>{
 expect(canonicalizeOutcomes([outcomes[2],outcomes[1],outcomes[0]],'ORD-1001')).toEqual(outcomes);
 const brief=synthesizeBrief('ORD-1001',outcomes);expect(brief.sections.map(s=>s.worker_id)).toEqual(['order-details','payment-status','delivery-status']);
 expect(brief.complete).toBe(true);expect(brief.missing_workers).toEqual([]);
 brief.sections[0]!.output.order_id='ORD-9999';expect(outcomes[0].output?.order_id).toBe('ORD-1001');
});
test('reject_incomplete_or_duplicate_fanin',()=>{
 for(const raw of [[outcomes[0]],[outcomes[0],outcomes[0],outcomes[2]],[...outcomes,{worker_id:'unknown'}],outcomes.map(o=>({...o,output:{...o.output,order_id:'ORD-9999'}}))])expect(()=>canonicalizeOutcomes(raw,'ORD-1001')).toThrow();
});
test('failed_reads_do_not_fabricate_sections',()=>{
 const brief=synthesizeBrief('ORD-1001',[outcomes[0],fail(1),fail(2)]);
 expect(brief.sections.map(s=>s.worker_id)).toEqual(['order-details']);expect(brief.missing_workers).toEqual(['payment-status','delivery-status']);expect(brief.complete).toBe(false);
 expect(()=>synthesizeBrief('ORD-1001',[fail(0),fail(1),fail(2)])).toThrow();
});
