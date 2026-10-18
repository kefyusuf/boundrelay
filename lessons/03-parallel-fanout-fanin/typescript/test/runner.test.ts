import {expect,test} from 'vitest';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join} from 'node:path';
import {runCase} from '../src/runner.js';import {loadScenario} from '../src/scenario.js';import {ScriptedWorkers} from '../src/scripted-workers.js';import {createWorkerDirectory} from '../src/workers.js';import {synthesizeBrief} from '../src/synthesizer.js';
function fixture(){const s=loadScenario();const p=new ScriptedWorkers(s.cases[1]!,s.order_id);return {p,directory:createWorkerDirectory(p)};}
test('synthesis_waits_for_all_outcomes',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m3-'));try{
 const h=fixture();const original=h.directory.resolve.bind(h.directory);let release!:()=>void,entered!:()=>void,calls=0;
 const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>entered=r);
 h.directory.resolve=id=>{const w=original(id)!;return {...w,handle:async i=>{const value=await w.handle(i);if(id==='delivery-status'){entered();await gate;}return value;}};};
 const run=runCase({caseId:'parallel-complete',tracePath:join(dir,'held.jsonl'),directory:h.directory,control:h.p,synthesizer:(id,outcomes)=>{calls++;expect(outcomes.map(o=>o.worker_id)).toEqual(['order-details','payment-status','delivery-status']);return synthesizeBrief(id,outcomes);}});
 await arrival;expect(calls).toBe(0);release();expect((await run).status).toBe('SUCCEEDED');expect(calls).toBe(1);
 let failedCalls=0;const failed=await runCase({caseId:'parallel-all-failed',tracePath:join(dir,'failed.jsonl'),synthesizer:(id,o)=>{failedCalls++;return synthesizeBrief(id,o);}});
 expect(failedCalls).toBe(0);expect(failed.brief).toBeNull();expect(failed.synthesis_invoked).toBe(false);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('trace_rejects_raw_private_payload',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m3-'));try{
 const h=fixture(),original=h.directory.resolve.bind(h.directory);h.directory.resolve=id=>{const w=original(id)!;return {...w,handle:async i=>{const value=await w.handle(i);return id==='payment-status'?{...(value as object),private:'PRIVATE-PAYLOAD'}:value;}};};
 const path=join(dir,'private.jsonl'),r=await runCase({caseId:'parallel-complete',tracePath:path,directory:h.directory,control:h.p});
 expect(r.status).toBe('PARTIAL');expect(r.worker_outcomes[1].failure_code).toBe('INVALID_WORKER_OUTPUT');expect(r.brief?.missing_workers).toEqual(['payment-status']);expect(readFileSync(path,'utf8')).not.toContain('PRIVATE-PAYLOAD');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('fatal_run_flushes_prefix_without_result',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m3-'));try{
 const h=fixture(),original=h.directory.resolve.bind(h.directory);h.directory.resolve=id=>{const w=original(id)!;return {...w,handle:async i=>{const v=await w.handle(i);if(id==='order-details')throw new Error('unexpected');return v;}};};
 const path=join(dir,'fatal.jsonl');await expect(runCase({caseId:'parallel-complete',tracePath:path,directory:h.directory,control:h.p})).rejects.toThrow('unexpected');
 const events=readFileSync(path,'utf8').trim().split('\n').map(v=>JSON.parse(v));expect(events[0].type).toBe('run.created');expect(events.some(e=>['run.completed','run.failed'].includes(e.type))).toBe(false);
 expect(events.some(e=>e.data.worker_id==='delivery-status')).toBe(false);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
