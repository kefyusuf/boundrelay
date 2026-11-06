import {describe,expect,test} from 'vitest';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {parseCliOptions,runCli} from '../src/cli.js';

describe('strict CLI parsing',()=>{
 test('accepts the documented option set',()=>{
  const options=parseCliOptions(['--case','parallel-complete','--trace','t.jsonl']);
  expect(options).toEqual({mode:'corrected',case_id:'parallel-complete',trace_path:'t.jsonl'});
  expect(parseCliOptions(['--mode','naive','--case','parallel-complete','--trace','t.jsonl']).mode).toBe('naive');
 });
 test('rejects invalid or missing arguments',()=>{
  const base=['--case','parallel-complete','--trace','t.jsonl'];
  const badArgs:string[][]=[
   [],
   base.slice(2),
   ['--mode','bogus',...base],
   [...base,'--case','other'],
   ['--case','--trace','x','y'],
   ['positional',...base],
   ['--case','x'],
   ['--trace','y']];
  for(const args of badArgs)expect(()=>parseCliOptions(args),JSON.stringify(args)).toThrow();
 });
});

describe('exit codes',()=>{
 test('domain results exit 0 with exactly one JSON result line on stdout',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-cli-'));
  try{
   let stdout='',stderr='';
   const code=await runCli(['--case','parallel-all-failed','--trace',join(dir,'all-failed.jsonl')],v=>stdout+=v,v=>stderr+=v);
   expect(code).toBe(0);
   expect(stderr).toBe('');
   const lines=stdout.trimEnd().split('\n');
   expect(lines).toHaveLength(1);
   const parsed=JSON.parse(lines[0]!) as {status:string;failure_code:string|null};
   expect(parsed.status).toBe('FAILED');
   expect(parsed.failure_code).toBe('ALL_WORKERS_FAILED');
  }finally{rmSync(dir,{recursive:true,force:true});}
 });
 test('tooling failures exit 2 with no canonical result on stdout',async()=>{
  let stdout='',stderr='';
  const code=await runCli(['--case','no-such-case','--trace','unused.jsonl'],v=>stdout+=v,v=>stderr+=v);
  expect(code).toBe(2);
  expect(stdout).toBe('');
  expect(stderr).not.toBe('');
 });
 test('unknown mode exits 2',async()=>{
  let stdout='';
  const code=await runCli(['--mode','bogus','--case','parallel-complete','--trace','x.jsonl'],v=>stdout+=v,()=>undefined);
  expect(code).toBe(2);
  expect(stdout).toBe('');
 });
});
