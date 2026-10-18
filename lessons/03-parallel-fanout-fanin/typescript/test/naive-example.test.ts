import {expect,test} from 'vitest';
import {executeWorkers} from '../src/executor.js';import {loadScenario} from '../src/scenario.js';import {ScriptedWorkers} from '../src/scripted-workers.js';import {createWorkerDirectory} from '../src/workers.js';import {canonicalizeOutcomes} from '../src/collector.js';import {synthesizeBrief} from '../src/synthesizer.js';
async function naiveReads(){
 const ids=['order-details','payment-status','delivery-status'],sections:string[]=[],release=new Map<string,()=>void>();let active=0,peak=0;
 const jobs=new Map(ids.map(id=>[id,(async()=>{active++;peak=Math.max(peak,active);await new Promise<void>(r=>release.set(id,r));sections.push(id);active--;})()]));
 for(const id of ['payment-status','delivery-status','order-details']){release.get(id)!();await jobs.get(id);}
 return {peak,sections};
}
test('naive_unbounded_reads_change_report_order',async()=>{
 const naive=await naiveReads();expect(naive.peak).toBe(3);expect(naive.sections).toEqual(['payment-status','delivery-status','order-details']);
 const s=loadScenario(),p=new ScriptedWorkers(s.cases[2]!,s.order_id);
 const corrected=await executeWorkers({mode:'parallel',input:{order_id:s.order_id},directory:createWorkerDirectory(p),control:p,observer:()=>{}});
 expect(corrected.peakConcurrency).toBe(2);expect(synthesizeBrief(s.order_id,canonicalizeOutcomes(corrected.outcomes,s.order_id)).sections.map(s=>s.worker_id)).toEqual(['order-details','payment-status','delivery-status']);
});
