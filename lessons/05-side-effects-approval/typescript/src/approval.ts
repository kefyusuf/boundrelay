import {effectDigest} from './idempotency.js';
import type {ApprovalMetadata,ApprovalRecord,EffectPayload} from './types.js';
export class ApprovalGate {
 constructor(private readonly metadata:ApprovalMetadata){}
 decide(payload:EffectPayload):{decision:'granted'|'rejected';record:ApprovalRecord} {
  const record:ApprovalRecord={operation:payload.operation,order_id:payload.order_id,
   payload_digest:effectDigest(payload),decision:this.metadata.decision,approver:this.metadata.approver};
  return {decision:this.metadata.decision,record};
 }
}
export function requireApproval(record:ApprovalRecord,payload:EffectPayload):void {
 if(record.operation!==payload.operation||record.order_id!==payload.order_id
  ||record.payload_digest!==effectDigest(payload))throw new Error('Approval binding mismatch');
 if(record.decision!=='granted')throw new Error('Approval not granted');
}
