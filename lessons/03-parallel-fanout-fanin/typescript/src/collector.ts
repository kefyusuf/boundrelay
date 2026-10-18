import {WORKER_IDS,type CanonicalOutcomes,type WorkerOutcome} from './types.js';
import {validateWorkerOutcome} from './schemas.js';
export function canonicalizeOutcomes(raw:readonly unknown[],orderId:string):CanonicalOutcomes{
 if(raw.length!==3||!raw.every(o=>validateWorkerOutcome(o,orderId)))throw new Error('Incomplete or invalid fan in');
 const outcomes=raw as readonly WorkerOutcome[];
 if(new Set(outcomes.map(o=>o.worker_id)).size!==3)throw new Error('Duplicate worker identity');
 return WORKER_IDS.map(id=>structuredClone(outcomes.find(o=>o.worker_id===id)!)) as unknown as CanonicalOutcomes;
}
