import {expect,test} from 'vitest';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runCase} from '../src/runner.js';
import {CrashSignal} from '../src/executor.js';
import {StateStore,loadRunState} from '../src/state-store.js';
import {loadScenario} from '../src/scenario.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
import {createWorkerDirectory} from '../src/workers.js';
import {synthesizeBrief} from '../src/synthesizer.js';
import type {StateBinding,WorkerDefinition,WorkerId} from '../src/types.js';
const binding=(caseId:string):StateBinding=>({case_id:caseId,execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2});
function fixture(caseId:string){
 const s=loadScenario();const spec=s.cases.find(c=>c.case_id===caseId)!;const p=new ScriptedWorkers(spec,s.order_id);
 return {p,directory:createWorkerDirectory(p)};
}
function wrapGate(h:{directory:ReturnType<typeof createWorkerDirectory>},workerId:WorkerId,hooks:{entered?:()=>void;gate?:Promise<void>;mutate?:(value:unknown)=>unknown}){
 const original=h.directory.resolve.bind(h.directory);
 h.directory.resolve=id=>{const w=original(id)!;return {...w,handle:async input=>{const value=await w.handle(input);if(id===workerId){hooks.entered?.();if(hooks.gate)await hooks.gate;return hooks.mutate?hooks.mutate(value):value;}return value;}} as WorkerDefinition;};
}
test('synthesis_waits_for_all_outcomes',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-'));try{
 const h=fixture('parallel-clean-complete');let release!:()=>void,entered!:()=>void,calls=0;
 const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>entered=r);
 wrapGate(h,'delivery-status',{entered,gate});
 const run=runCase({caseId:'parallel-clean-complete',tracePath:join(dir,'held.jsonl'),stateDir:join(dir,'state'),directory:h.directory,control:h.p,synthesizer:(id,outcomes)=>{calls++;expect(outcomes.map(o=>o.worker_id)).toEqual(['order-details','payment-status','delivery-status']);return synthesizeBrief(id,outcomes);}});
 await arrival;expect(calls).toBe(0);release();expect((await run).status).toBe('SUCCEEDED');expect(calls).toBe(1);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('trace_rejects_raw_private_payload',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-'));try{
 const h=fixture('parallel-clean-complete');wrapGate(h,'payment-status',{mutate:value=>({...((value as object)!),private:'PRIVATE-PAYLOAD'})});
 const path=join(dir,'private.jsonl'),r=await runCase({caseId:'parallel-clean-complete',tracePath:path,stateDir:join(dir,'state'),directory:h.directory,control:h.p});
 expect(r.status).toBe('PARTIAL');expect(r.worker_outcomes[1]!.failure_code).toBe('INVALID_WORKER_OUTPUT');
 expect(r.brief?.missing_workers).toEqual(['payment-status']);expect(readFileSync(path,'utf8')).not.toContain('PRIVATE-PAYLOAD');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('fatal_run_flushes_prefix_without_result',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-'));try{
 const h=fixture('parallel-clean-complete');wrapGate(h,'order-details',{mutate:()=>{throw new Error('unexpected');}});
 const path=join(dir,'fatal.jsonl');
 await expect(runCase({caseId:'parallel-clean-complete',tracePath:path,stateDir:join(dir,'state'),directory:h.directory,control:h.p})).rejects.toThrow('unexpected');
 const events=readFileSync(path,'utf8').trim().split('\n').map(v=>JSON.parse(v) as {type:string;data:Record<string,unknown>});
 expect(events[0]!.type).toBe('run.created');
 expect(events.some(e=>['run.completed','run.failed','run.cancelled'].includes(e.type))).toBe(false);
 expect(events.some(e=>e.data.worker_id==='delivery-status')).toBe(false);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('cancelled_run_is_domain_outcome',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-'));try{
 const path=join(dir,'cancel.jsonl'),stateDir=join(dir,'state');
 const r=await runCase({caseId:'parallel-cancel-resume',tracePath:path,stateDir});
 expect(r.status).toBe('CANCELLED');expect(r.failure_code).toBeNull();expect(r.synthesis_invoked).toBe(false);expect(r.brief).toBeNull();
 expect(r.run_state_status).toBe('CANCELLED');expect(r.resumed).toBe(false);expect(r.restored_cursor).toBeNull();expect(r.restored_worker_ids).toEqual([]);
 const events=readFileSync(path,'utf8').trim().split('\n').map(v=>JSON.parse(v) as {type:string;data:Record<string,unknown>});
 const cancelled=events.find(e=>e.type==='run.cancelled')!;
 expect(cancelled.data.cancelled_before).toBe('delivery-status');expect(cancelled.data.code).toBe('CANCELLED_BEFORE_STEP');
 expect(events.some(e=>['run.completed','run.failed'].includes(e.type))).toBe(false);
 const document=loadRunState(stateDir,binding('parallel-cancel-resume')).document;
 expect(document.status).toBe('CANCELLED');expect(document.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','CANCELLED']);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('crash_phase_flushes_prefix_without_terminal',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-'));try{
 const path=join(dir,'crash.jsonl'),stateDir=join(dir,'state');let crashes=0;
 const run=runCase({caseId:'parallel-crash-resume',tracePath:path,stateDir,on_crash:()=>{crashes++;throw new CrashSignal('crash');}}).then(()=>null,error=>error);
 expect(await run).toBeInstanceOf(CrashSignal);expect(crashes).toBe(1);
 const events=readFileSync(path,'utf8').trim().split('\n').map(v=>JSON.parse(v) as {type:string;data:Record<string,unknown>});
 expect(events[0]!.type).toBe('run.created');expect(events[events.length-1]!.type).toBe('checkpoint.saved');
 expect(events.some(e=>['run.completed','run.failed','run.cancelled'].includes(e.type))).toBe(false);
 expect(events.some(e=>String(e.data.step_name)==='worker.delivery-status')).toBe(false);
 const document=loadRunState(stateDir,binding('parallel-crash-resume')).document;
 expect(document.status).toBe('RUNNING');expect(document.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','PENDING']);expect(document.sequence_cursor).toBe(2);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
