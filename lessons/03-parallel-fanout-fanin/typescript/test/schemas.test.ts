import {expect,test} from 'vitest';
import {validateWorkerOutput} from '../src/schemas.js';
test('reject_original_invalid_output',()=>{
 const cycle:Record<string,unknown>={};cycle.self=cycle;
 const valid={order_id:'ORD-1001',payment_status:'PAID'};
 expect(validateWorkerOutput('payment-status',valid,'ORD-1001')).toEqual({valid:true,value:valid});
 for(const raw of [{...valid,private:'secret'},{...valid,order_id:'ORD-9999'},{...valid,payment_status:'UNKNOWN'},NaN,Infinity,cycle,{...valid,n:2**54}])
  expect(validateWorkerOutput('payment-status',raw,'ORD-1001')).toEqual({valid:false});
});
