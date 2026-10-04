import {expect,test} from 'vitest';
import {validateWorkerOutput} from '../src/schemas.js';
test('reject_original_invalid_output',()=>{
 const cycle:Record<string,unknown>={};cycle.self=cycle;
 const valid={order_id:'ORD-1001',payment_status:'PAID'};
 expect(validateWorkerOutput('payment-status',valid,'ORD-1001')).toEqual({valid:true,value:valid});
 for(const raw of [{...valid,private:'secret'},{...valid,order_id:'ORD-9999'},{...valid,payment_status:'UNKNOWN'},NaN,Infinity,cycle,{...valid,n:2**54}])
  expect(validateWorkerOutput('payment-status',raw,'ORD-1001')).toEqual({valid:false});
});
test('reject_hidden_symbol_and_accessor_fields_without_evaluating_them',()=>{
 const valid={order_id:'ORD-1001',payment_status:'PAID'};
 const symbol={...valid,[Symbol('private')]:()=> 'secret'};
 const hidden=Object.defineProperty({...valid},'private',{value:'secret',enumerable:false});
 let reads=0;
 const accessor=Object.defineProperty({...valid},'private',{get(){reads++;return 'secret';},enumerable:true});
 for(const raw of [symbol,hidden,accessor])expect(validateWorkerOutput('payment-status',raw,'ORD-1001')).toEqual({valid:false});
 expect(reads).toBe(0);
});
