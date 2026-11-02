import {expect,test} from 'vitest';
import {ApprovalGate,requireApproval} from '../src/approval.js';
import {effectDigest} from '../src/idempotency.js';
import type {ApprovalRecord,EffectPayload} from '../src/types.js';
const PAYLOAD:EffectPayload={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'};
test('approval_binds_to_payload_digest',()=>{
 const gate=new ApprovalGate({decision:'granted',approver:'approver-primary'});
 const granted=gate.decide(PAYLOAD);
 expect(granted.decision).toBe('granted');
 const record:ApprovalRecord=granted.record;
 expect(record).toEqual({operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:effectDigest(PAYLOAD),decision:'granted',approver:'approver-primary'});
 const rejectedGate=new ApprovalGate({decision:'rejected',approver:'approver-primary'});
 const rejected=rejectedGate.decide(PAYLOAD);
 expect(rejected.decision).toBe('rejected');
 expect(rejected.record.decision).toBe('rejected');
 expect(rejected.record.payload_digest).toBe(effectDigest(PAYLOAD));
 expect(()=>requireApproval(rejected.record,PAYLOAD)).toThrow('Approval not granted');
});
test('require_approval_raises_on_binding_mismatch',()=>{
 const gate=new ApprovalGate({decision:'granted',approver:'approver-primary'});
 const {record}=gate.decide(PAYLOAD);
 requireApproval(record,PAYLOAD);
 expect(()=>requireApproval({...record,payload_digest:'d'.repeat(64)},PAYLOAD)).toThrow('Approval binding mismatch');
 expect(()=>requireApproval({...record,operation:'cancel' as 'cancel-and-refund'},PAYLOAD)).toThrow('Approval binding mismatch');
 expect(()=>requireApproval({...record,order_id:'ORD-1002'},PAYLOAD)).toThrow('Approval binding mismatch');
});
