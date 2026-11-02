import {expect,test} from 'vitest';
import {WORKER_IDS,type CaseSpec} from '../src/types.js';
import {loadScenario} from '../src/scenario.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
const raiseSpec:CaseSpec={case_id:'scripted-raise-test',execution_mode:'parallel',worker_fixture:'fixtures/workers/order-brief/all-failed.yaml',completion_order:[...WORKER_IDS],approval:{decision:'granted',approver:'approver-primary'}};
test('release_requires_entry_and_recorded_ack',async()=>{
 const s=loadScenario();const p=new ScriptedWorkers(s.cases[1]!,s.order_id);const input={order_id:'ORD-1001'};
 let orderDone=false,paymentDone=false;
 const a=p.read('order-details',input).then(v=>{orderDone=true;return v;});
 await Promise.resolve();expect(orderDone).toBe(false);
 const b=p.read('payment-status',input).then(v=>{paymentDone=true;return v;});
 await a;expect(paymentDone).toBe(false);
 p.acknowledgeOutcome('order-details');await b;expect(paymentDone).toBe(true);
 expect(()=>p.acknowledgeOutcome('order-details')).toThrow();
 const drain=new ScriptedWorkers(s.cases[1]!,s.order_id);
 const x=drain.read('order-details',input);const y=drain.read('payment-status',input);
 await x;drain.beginDrain();await y;
 await expect(drain.read('delivery-status',input)).rejects.toThrow();
});
test('declared_worker_failures_raise_worker_execution_error',async()=>{
 const p=new ScriptedWorkers(raiseSpec,'ORD-1001');const input={order_id:'ORD-1001'};
 const a=p.read('order-details',input);const b=p.read('payment-status',input);
 await expect(a).rejects.toThrow('Declared worker failure');
 p.acknowledgeOutcome('order-details');
 await expect(b).rejects.toThrow('Declared worker failure');
});
