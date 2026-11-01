import {canonicalizeOutcomes} from './collector.js';
import type {Brief,CanonicalOutcomes} from './types.js';
export function synthesizeBrief(orderId:string,outcomes:CanonicalOutcomes):Brief {
 const canonical=canonicalizeOutcomes(outcomes,orderId);
 const sections=canonical.flatMap(o=>o.status==='SUCCEEDED'?[{worker_id:o.worker_id,output:o.output}]:[]);
 if(sections.length===0)throw new Error('Cannot synthesize without successful evidence');
 const missing_workers=canonical.filter(o=>o.status==='FAILED').map(o=>o.worker_id);
 return {order_id:orderId,sections,missing_workers,complete:missing_workers.length===0};
}
