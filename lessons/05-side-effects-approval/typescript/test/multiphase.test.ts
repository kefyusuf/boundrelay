import {expect,test} from 'vitest';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {EffectLedger} from '../src/effect-ledger.js';
import {AuditWriter} from '../src/audit.js';
const cwd=fileURLToPath(new URL('..',import.meta.url));
function spawn(args:string[]):{code:number;stdout:string;stderr:string} {
 try{const stdout=execFileSync(process.execPath,['--import','tsx','src/cli.ts',...args],{cwd,encoding:'utf8',timeout:120000});return {code:0,stdout,stderr:''};}
 catch(error){const failure=error as {status?:number;stdout?:string;stderr?:string};return {code:failure.status??-1,stdout:failure.stdout??'',stderr:failure.stderr??''};}
}
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m5-mp-'));}
function traceEvents(path:string):{type:string;data:Record<string,unknown>}[] {return readFileSync(path,'utf8').trim().split('\n').map(line=>JSON.parse(line) as {type:string;data:Record<string,unknown>});}
test('approval_granted_effect_once_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace=join(root,'run.jsonl');
 try{
  const phase=spawn(['--case','approval-granted-effect-once','--trace',trace,'--state-dir',stateDir]);
  expect(phase.code).toBe(0);
  const result=JSON.parse(phase.stdout.trim()) as Record<string,unknown>;
  expect(result.status).toBe('SUCCEEDED');expect(result.approval_decision).toBe('granted');
  expect(result.effect_status).toBe('EFFECT_COMPLETED');expect(result.reconciled).toBe(false);
  expect(phase.stdout.trim().split('\n')).toHaveLength(1);
  expect(new EffectLedger(stateDir).records()).toHaveLength(1);
  const order=traceEvents(trace).map(e=>e.type);
  expect(order.indexOf('approval.granted')).toBeLessThan(order.indexOf('tool.requested'));
  expect(order.indexOf('tool.completed')).toBeLessThan(order.indexOf('run.completed'));
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('approval_rejected_no_effect_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace=join(root,'run.jsonl');
 try{
  const phase=spawn(['--case','approval-rejected-no-effect','--trace',trace,'--state-dir',stateDir]);
  expect(phase.code).toBe(0);
  const result=JSON.parse(phase.stdout.trim()) as Record<string,unknown>;
  expect(result.status).toBe('FAILED');expect(result.failure_code).toBe('APPROVAL_REJECTED');
  expect(new EffectLedger(stateDir).records()).toEqual([]);
  const audit=new AuditWriter(stateDir).records();
  expect(audit).toHaveLength(1);expect(audit[0]).toMatchObject({kind:'approval',decision:'rejected'});
  expect(traceEvents(trace).some(e=>e.type.startsWith('tool.'))).toBe(false);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('retry_before_submit_two_phase_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  const phase1=spawn(['--case','retry-before-submit','--trace',trace1,'--state-dir',stateDir]);
  expect(phase1.code).toBe(2);expect(phase1.stdout).toBe('');
  const events=traceEvents(trace1);
  expect(events[0]!.type).toBe('run.created');
  expect(events.some(e=>e.type==='approval.granted')).toBe(true);
  expect(events.some(e=>e.type.startsWith('tool.'))).toBe(false);
  expect(events.some(e=>['run.completed','run.failed'].includes(e.type))).toBe(false);
  const phase2=spawn(['--case','retry-before-submit','--trace',trace2,'--state-dir',stateDir,'--resume']);
  expect(phase2.code).toBe(0);
  const result=JSON.parse(phase2.stdout.trim()) as Record<string,unknown>;
  expect(result.status).toBe('SUCCEEDED');expect(result.reconciled).toBe(false);expect(result.resumed).toBe(true);
  expect(new EffectLedger(stateDir).records()).toHaveLength(1);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('crash_submit_window_resolved_two_phase_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  const phase1=spawn(['--case','crash-submit-window-resolved','--trace',trace1,'--state-dir',stateDir]);
  expect(phase1.code).toBe(2);expect(phase1.stdout).toBe('');
  expect(traceEvents(trace1).some(e=>e.type==='tool.requested')).toBe(true);
  const phase2=spawn(['--case','crash-submit-window-resolved','--trace',trace2,'--state-dir',stateDir,'--resume']);
  expect(phase2.code).toBe(0);
  const result=JSON.parse(phase2.stdout.trim()) as Record<string,unknown>;
  expect(result.status).toBe('SUCCEEDED');expect(result.reconciled).toBe(true);expect(result.resumed).toBe(true);
  expect(new EffectLedger(stateDir).records()).toHaveLength(1);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('sink_unavailable_unknown_two_phase_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  expect(spawn(['--case','sink-unavailable-unknown','--trace',trace1,'--state-dir',stateDir]).code).toBe(2);
  const phase2=spawn(['--case','sink-unavailable-unknown','--trace',trace2,'--state-dir',stateDir,'--resume']);
  expect(phase2.code).toBe(0);
  const result=JSON.parse(phase2.stdout.trim()) as Record<string,unknown>;
  expect(result.status).toBe('UNKNOWN');expect(result.effect_status).toBe('EFFECT_UNPROVABLE');
  expect(result.failure_code).toBeNull();expect(result.reconciled).toBe(false);
  expect(result.run_state_status).toBe('UNKNOWN');expect(result.idempotency_key).toBe('cancel-and-refund:ORD-1001');
  expect(new EffectLedger(stateDir).records()).toHaveLength(1);
  expect(traceEvents(trace2).some(e=>['run.completed','run.failed'].includes(e.type))).toBe(true);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('duplicate_key_suppressed_two_runs_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'run1.jsonl'),trace2=join(root,'run2.jsonl');
 try{
  const first=spawn(['--case','duplicate-key-suppressed','--trace',trace1,'--state-dir',stateDir]);
  expect(first.code).toBe(0);
  const one=JSON.parse(first.stdout.trim()) as Record<string,unknown>;
  expect(one.status).toBe('SUCCEEDED');expect(one.reconciled).toBe(false);
  const second=spawn(['--case','duplicate-key-suppressed','--trace',trace2,'--state-dir',stateDir]);
  expect(second.code).toBe(0);
  const two=JSON.parse(second.stdout.trim()) as Record<string,unknown>;
  expect(two.status).toBe('SUCCEEDED');expect(two.reconciled).toBe(false);
  expect(two.idempotency_key).toBe('cancel-and-refund:ORD-1001');
  expect(new EffectLedger(stateDir).records()).toHaveLength(1);
  const doc=JSON.parse(readFileSync(join(stateDir,String(two.run_id),'state.json'),'utf8')) as {effect:{duplicate:boolean}|null};
  expect(doc.effect!.duplicate).toBe(true);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);


