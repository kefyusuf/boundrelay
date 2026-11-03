import {expect,test} from 'vitest';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runCase} from '../src/runner.js';
import {CrashSignal} from '../src/executor.js';
import {loadRunState} from '../src/state-store.js';
import {loadScenario} from '../src/scenario.js';
import {ScriptedWorkers} from '../src/scripted-workers.js';
import {createWorkerDirectory} from '../src/workers.js';
import {effectDigest,effectKey} from '../src/idempotency.js';
import {EffectLedger} from '../src/effect-ledger.js';
import {AuditWriter} from '../src/audit.js';
function spyLedgerRecords(stateDir:string){return new EffectLedger(stateDir).records();}
function spyAuditRecords(stateDir:string){return new AuditWriter(stateDir).records();}
import type {StateBinding,WorkerDefinition,WorkerId} from '../src/types.js';
const PAYLOAD={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'} as const;
const KEY=effectKey(PAYLOAD),DIGEST=effectDigest(PAYLOAD);
const BINDING:StateBinding={case_id:'approval-granted-effect-once',execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2};
const bindingFor=(caseId:string):StateBinding=>({...BINDING,case_id:caseId});
type Event={type:string;data:Record<string,unknown>};
function events(path:string):Event[] {return readFileSync(path,'utf8').trim().split('\n').map(line=>JSON.parse(line) as Event);}
function fixture(caseId:string){
 const s=loadScenario();const spec=s.cases.find(c=>c.case_id===caseId)!;const p=new ScriptedWorkers(spec,s.order_id);
 return {p,directory:createWorkerDirectory(p)};
}
function wrapGate(h:{directory:ReturnType<typeof createWorkerDirectory>},workerId:WorkerId,mutate?:(value:unknown)=>unknown){
 const original=h.directory.resolve.bind(h.directory);
 h.directory.resolve=id=>{const w=original(id)!;return {...w,handle:async input=>{const value=await w.handle(input);if(id===workerId&&mutate)return mutate(value);return value;}} as WorkerDefinition;};
}
test('granted_run_emits_approval_and_tool_events_in_order',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const path=join(dir,'run.jsonl'),stateDir=join(dir,'state');
 const result=await runCase({caseId:'approval-granted-effect-once',tracePath:path,stateDir});
 expect(result.status).toBe('SUCCEEDED');expect(result.failure_code).toBeNull();
 expect(result.approval_decision).toBe('granted');expect(result.effect_status).toBe('EFFECT_COMPLETED');
 expect(result.idempotency_key).toBe(KEY);expect(result.reconciled).toBe(false);
 expect(result.synthesis_invoked).toBe(false);expect(result.brief).toBeNull();
 expect(result.resumed).toBe(false);expect(result.restored_cursor).toBeNull();
 expect(result.run_state_status).toBe('SUCCEEDED');expect(result.peak_concurrency).toBe(2);
 const list=events(path);
 expect(list[0]!.type).toBe('run.created');expect(list[1]!.type).toBe('run.started');
 expect(list[0]!.data).toEqual({scenario_id:'order-closure',case_id:'approval-granted-effect-once',execution_mode:'parallel',order_id:'ORD-1001',concurrency_limit:2,state_dir:stateDir});
 const approval=list.filter(e=>e.type.startsWith('approval.'));
 expect(approval.map(e=>e.type)).toEqual(['approval.requested','approval.granted']);
 expect(approval[0]!.data).toEqual({operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:DIGEST});
 const tool=list.filter(e=>e.type.startsWith('tool.'));
 expect(tool.map(e=>e.type)).toEqual(['tool.requested','tool.completed']);
 expect(tool[0]!.data).toEqual({key:KEY,payload_digest:DIGEST,side_effect_class:'external'});
 expect(tool[1]!.data).toEqual({key:KEY,status:'EFFECT_COMPLETED',duplicate:false});
 const order=list.map(e=>e.type);
 expect(order.indexOf('approval.granted')).toBeLessThan(order.indexOf('tool.requested'));
 expect(order.indexOf('tool.requested')).toBeLessThan(order.indexOf('tool.completed'));
 expect(order.indexOf('tool.completed')).toBeLessThan(order.indexOf('run.completed'));
 const terminal=list[list.length-1]!;
 expect(terminal.type).toBe('run.completed');
 expect(terminal.data).toEqual({status:'SUCCEEDED',worker_outcomes:result.worker_outcomes,synthesis_invoked:false,brief:null,failure_code:null,peak_concurrency:2,reconciled:false,approval_decision:'granted',effect_status:'EFFECT_COMPLETED',idempotency_key:KEY});
 expect(spyLedgerRecords(stateDir)).toHaveLength(1);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('rejected_run_has_zero_submissions_and_records_rejection',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const path=join(dir,'rejected.jsonl'),stateDir=join(dir,'state');
 const result=await runCase({caseId:'approval-rejected-no-effect',tracePath:path,stateDir});
 expect(result.status).toBe('FAILED');expect(result.failure_code).toBe('APPROVAL_REJECTED');
 expect(result.approval_decision).toBe('rejected');expect(result.effect_status).toBeNull();
 expect(result.idempotency_key).toBeNull();expect(result.reconciled).toBe(false);
 expect(result.run_state_status).toBe('FAILED');
 expect(spyLedgerRecords(stateDir)).toEqual([]);
 const audit=spyAuditRecords(stateDir);
 expect(audit).toEqual([{kind:'approval',operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:DIGEST,decision:'rejected',approver:'approver-primary'}]);
 const list=events(path);
 expect(list.filter(e=>e.type.startsWith('tool.'))).toEqual([]);
 expect(list.filter(e=>e.type.startsWith('approval.')).map(e=>e.type)).toEqual(['approval.requested','approval.rejected']);
 expect(list[list.length-1]!.type).toBe('run.failed');
 const document=loadRunState(stateDir,bindingFor('approval-rejected-no-effect')).document;
 expect(document.status).toBe('FAILED');expect(document.submit_marker).toBeNull();
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('failed_reads_stop_before_approval_events',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const h=fixture('approval-granted-effect-once');
 wrapGate(h,'payment-status',value=>({...((value as object)!),private:'PRIVATE-PAYLOAD'}));
 const path=join(dir,'partial.jsonl'),stateDir=join(dir,'state');
 const result=await runCase({caseId:'approval-granted-effect-once',tracePath:path,stateDir,directory:h.directory,control:h.p});
 expect(result.status).toBe('PARTIAL');expect(result.failure_code).toBeNull();
 expect(result.approval_decision).toBe('none');expect(result.effect_status).toBeNull();
 expect(result.idempotency_key).toBeNull();expect(result.reconciled).toBe(false);
 const list=events(path);
 expect(list.filter(e=>e.type.startsWith('approval.'))).toEqual([]);
 expect(list.filter(e=>e.type.startsWith('tool.'))).toEqual([]);
 expect(readFileSync(path,'utf8')).not.toContain('PRIVATE-PAYLOAD');
 expect(spyLedgerRecords(stateDir)).toEqual([]);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('crash_phase_flushes_prefix_without_terminal',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const path=join(dir,'crash.jsonl'),stateDir=join(dir,'state');let crashes=0;
 const run=runCase({caseId:'crash-submit-window-resolved',tracePath:path,stateDir,on_crash:()=>{crashes++;throw new CrashSignal('crash');}}).then(()=>null,error=>error);
 expect(await run).toBeInstanceOf(CrashSignal);expect(crashes).toBe(1);
 const list=events(path);
 expect(list[0]!.type).toBe('run.created');
 expect(list.some(e=>e.type==='tool.requested')).toBe(true);
 expect(list.some(e=>e.type==='tool.completed')).toBe(false);
 expect(list.some(e=>['run.completed','run.failed'].includes(e.type))).toBe(false);
 const document=loadRunState(stateDir,bindingFor('crash-submit-window-resolved')).document;
 expect(document.status).toBe('RUNNING');
 expect(document.submit_marker).toEqual({key:KEY,payload_digest:DIGEST});
 expect(document.effect).toBeNull();
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('resume_completes_with_reconciled_adoption',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const crashPath=join(dir,'crash.jsonl'),resumePath=join(dir,'resume.jsonl'),stateDir=join(dir,'state');
 await runCase({caseId:'crash-submit-window-resolved',tracePath:crashPath,stateDir,on_crash:()=>{throw new CrashSignal('crash');}}).then(()=>undefined,error=>{if(!(error instanceof CrashSignal))throw error;});
 const result=await runCase({caseId:'crash-submit-window-resolved',tracePath:resumePath,stateDir,resume:true});
 expect(result.status).toBe('SUCCEEDED');expect(result.reconciled).toBe(true);
 expect(result.approval_decision).toBe('granted');expect(result.effect_status).toBe('EFFECT_COMPLETED');
 expect(result.idempotency_key).toBe(KEY);expect(result.resumed).toBe(true);
 expect(result.restored_cursor).toBe(3);expect(result.restored_worker_ids).toEqual([...['order-details','payment-status','delivery-status']]);
 expect(spyLedgerRecords(stateDir)).toHaveLength(1);
 const document=loadRunState(stateDir,bindingFor('crash-submit-window-resolved')).document;
 expect(document.status).toBe('SUCCEEDED');expect(document.effect).not.toBeNull();
 const terminal=events(resumePath)[events(resumePath).length-1]!;
 expect(terminal.type).toBe('run.completed');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('resume_unknown_stays_unknown_with_sink_unavailable',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const crashPath=join(dir,'crash.jsonl'),resumePath=join(dir,'resume.jsonl'),stateDir=join(dir,'state');
 await runCase({caseId:'sink-unavailable-unknown',tracePath:crashPath,stateDir,on_crash:()=>{throw new CrashSignal('crash');}}).then(()=>undefined,error=>{if(!(error instanceof CrashSignal))throw error;});
 const result=await runCase({caseId:'sink-unavailable-unknown',tracePath:resumePath,stateDir,resume:true});
 expect(result.status).toBe('UNKNOWN');expect(result.reconciled).toBe(false);
 expect(result.approval_decision).toBe('granted');expect(result.effect_status).toBe('EFFECT_UNPROVABLE');
 expect(result.idempotency_key).toBe(KEY);expect(result.failure_code).toBeNull();
 expect(result.run_state_status).toBe('UNKNOWN');expect(result.resumed).toBe(true);
 expect(spyLedgerRecords(stateDir)).toHaveLength(1);
 const document=loadRunState(stateDir,bindingFor('sink-unavailable-unknown')).document;
 expect(document.status).toBe('UNKNOWN');expect(document.effect).toBeNull();
 expect(events(resumePath)[events(resumePath).length-1]!.type).toBe('run.completed');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
test('resume_before_submit_reruns_the_effect_pipeline',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'br-m5-run-'));try{
 const crashPath=join(dir,'crash.jsonl'),resumePath=join(dir,'resume.jsonl'),stateDir=join(dir,'state');
 await runCase({caseId:'retry-before-submit',tracePath:crashPath,stateDir,on_crash:()=>{throw new CrashSignal('crash');}}).then(()=>undefined,error=>{if(!(error instanceof CrashSignal))throw error;});
 const crashed=loadRunState(stateDir,bindingFor('retry-before-submit')).document;
 expect(crashed.submit_marker).toBeNull();expect(crashed.effect).toBeNull();
 const result=await runCase({caseId:'retry-before-submit',tracePath:resumePath,stateDir,resume:true});
 expect(result.status).toBe('SUCCEEDED');expect(result.reconciled).toBe(false);
 expect(result.effect_status).toBe('EFFECT_COMPLETED');expect(result.idempotency_key).toBe(KEY);
 expect(result.resumed).toBe(true);expect(result.restored_cursor).toBe(3);
 expect(spyLedgerRecords(stateDir)).toHaveLength(1);
 const resume=events(resumePath);
 expect(resume.some(e=>e.type==='approval.granted')).toBe(true);
 expect(resume.some(e=>e.type==='tool.completed')).toBe(true);
 expect(resume[resume.length-1]!.type).toBe('run.completed');
 }finally{rmSync(dir,{recursive:true,force:true});}
});




