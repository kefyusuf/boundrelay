import {expect,test} from 'vitest';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadRunState} from '../src/state-store.js';
import type {StateBinding} from '../src/types.js';
const cwd=fileURLToPath(new URL('..',import.meta.url));
const binding=(caseId:string):StateBinding=>({case_id:caseId,execution_mode:'parallel',requested_order_id:'ORD-1001',concurrency_limit:2});
function spawn(args:string[]):{code:number;stdout:string;stderr:string} {
 try{const stdout=execFileSync(process.execPath,['--import','tsx','src/cli.ts',...args],{cwd,encoding:'utf8',timeout:120000});return {code:0,stdout,stderr:''};}
 catch(error){const failure=error as {status?:number;stdout?:string;stderr?:string};return {code:failure.status??-1,stdout:failure.stdout??'',stderr:failure.stderr??''};}
}
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m5-mp-'));}
function traceEvents(path:string):{type:string;data:Record<string,unknown>}[] {return readFileSync(path,'utf8').trim().split('\n').map(line=>JSON.parse(line) as {type:string;data:Record<string,unknown>});}
test('crash_resume_two_phase_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  const phase1=spawn(['--case','parallel-crash-resume','--trace',trace1,'--state-dir',stateDir]);
  expect(phase1.code).toBe(2);expect(phase1.stdout).toBe('');
  const events=traceEvents(trace1);
  expect(events[0]!.type).toBe('run.created');expect(events[events.length-1]!.type).toBe('checkpoint.saved');
  expect(events.some(e=>['run.completed','run.failed','run.cancelled'].includes(e.type))).toBe(false);
  const document=loadRunState(stateDir,binding('parallel-crash-resume')).document;
  expect(document.status).toBe('RUNNING');expect(document.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','PENDING']);expect(document.sequence_cursor).toBe(2);
  const phase2=spawn(['--case','parallel-crash-resume','--trace',trace2,'--state-dir',stateDir,'--resume']);
  expect(phase2.code).toBe(0);expect(phase2.stdout.trim().split('\n')).toHaveLength(1);
  const result=JSON.parse(phase2.stdout.trim()) as Record<string,unknown>;
  expect(result.status).toBe('SUCCEEDED');expect(result.resumed).toBe(true);expect(result.restored_cursor).toBe(2);
  expect(result.restored_worker_ids).toEqual(['order-details','payment-status']);expect(result.run_state_status).toBe('SUCCEEDED');
  expect(loadRunState(stateDir,binding('parallel-crash-resume')).document.status).toBe('SUCCEEDED');
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('cancel_resume_two_phase_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  const phase1=spawn(['--case','parallel-cancel-resume','--trace',trace1,'--state-dir',stateDir]);
  expect(phase1.code).toBe(0);
  const first=JSON.parse(phase1.stdout.trim()) as Record<string,unknown>;
  expect(first.status).toBe('CANCELLED');expect(first.failure_code).toBeNull();expect(first.synthesis_invoked).toBe(false);
  expect(traceEvents(trace1).some(e=>e.type==='run.cancelled')).toBe(true);
  const document=loadRunState(stateDir,binding('parallel-cancel-resume')).document;
  expect(document.status).toBe('CANCELLED');expect(document.steps.map(s=>s.status)).toEqual(['SUCCEEDED','SUCCEEDED','CANCELLED']);
  const phase2=spawn(['--case','parallel-cancel-resume','--trace',trace2,'--state-dir',stateDir,'--resume']);
  expect(phase2.code).toBe(0);
  const second=JSON.parse(phase2.stdout.trim()) as Record<string,unknown>;
  expect(second.status).toBe('SUCCEEDED');expect(second.resumed).toBe(true);expect(second.restored_cursor).toBe(2);
  expect(second.restored_worker_ids).toEqual(['order-details','payment-status']);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('replay_from_checkpoint_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  const phase1=spawn(['--case','parallel-replay-from-checkpoint','--trace',trace1,'--state-dir',stateDir]);
  expect(phase1.code).toBe(0);
  const first=JSON.parse(phase1.stdout.trim()) as {run_id:string};
  const runDir=join(stateDir,first.run_id),snapshot=join(runDir,'checkpoints','step-1.json');
  const beforeState=readFileSync(join(runDir,'state.json'),'utf8'),beforeSnapshot=readFileSync(snapshot,'utf8');
  const phase2=spawn(['--case','parallel-replay-from-checkpoint','--trace',trace2,'--state-dir',stateDir,'--replay-from',snapshot]);
  expect(phase2.code).toBe(0);
  const second=JSON.parse(phase2.stdout.trim()) as {run_id:string;status:string;resumed:boolean;restored_cursor:number;restored_worker_ids:string[]};
  expect(second.run_id).not.toBe(first.run_id);expect(second.status).toBe('SUCCEEDED');
  expect(second.resumed).toBe(true);expect(second.restored_cursor).toBe(1);expect(second.restored_worker_ids).toEqual(['order-details']);
  expect(readFileSync(join(runDir,'state.json'),'utf8')).toBe(beforeState);expect(readFileSync(snapshot,'utf8')).toBe(beforeSnapshot);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
test('corrupt_state_resume_fails_closed_subprocess',()=>{
 const root=freshRoot();const stateDir=join(root,'state'),trace1=join(root,'phase1.jsonl'),trace2=join(root,'phase2.jsonl');
 try{
  expect(spawn(['--case','parallel-crash-resume','--trace',trace1,'--state-dir',stateDir]).code).toBe(2);
  const statePath=loadRunState(stateDir,binding('parallel-crash-resume')).restored_from;
  const tampered=JSON.parse(readFileSync(statePath,'utf8')) as {steps:{output:{payment_status:string}|null}[]};
  tampered.steps[1]!.output!.payment_status='UNPAID';
  writeFileSync(statePath,JSON.stringify(tampered));
  const tamperedBytes=readFileSync(statePath,'utf8');
  const phase2=spawn(['--case','parallel-crash-resume','--trace',trace2,'--state-dir',stateDir,'--resume']);
  expect(phase2.code).toBe(2);expect(phase2.stdout).toBe('');expect(phase2.stderr).not.toBe('');
  expect(readFileSync(statePath,'utf8')).toBe(tamperedBytes);
 }finally{rmSync(root,{recursive:true,force:true});}
},120000);
