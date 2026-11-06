import {describe,expect,test} from 'vitest';
import Ajv2020 from 'ajv/dist/2020.js';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {runCorrected} from '../src/mapping.js';
import {loadGolden,PARITY_CASE_KEYS} from '../src/fixtures.js';

const REPO_ROOT=fileURLToPath(new URL('../../../../',import.meta.url));
const ajv=new Ajv2020({strict:false});
const validateResultSchema=ajv.compile(JSON.parse(readFileSync(REPO_ROOT+'contracts/results/order-brief-result.schema.json','utf8')));

const withTempTrace=async(fn:(trace:string)=>Promise<void>):Promise<void>=>{
 const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-'));
 try{await fn(join(dir,'native-stream.jsonl'));}finally{rmSync(dir,{recursive:true,force:true});}
};

describe('six-case parity against the M3 goldens',()=>{
 for(const key of PARITY_CASE_KEYS){
  test(`case ${key} reproduces the golden result_projection`,async()=>{
   await withTempTrace(async trace=>{
    const result=await runCorrected(key,trace);
    const {run_id:_runId,trace_path:_tracePath,...projection}=result;
    expect(projection).toEqual(loadGolden(key));
   });
  });
 }
 test('every published result is valid against the checked-in closed schema',async()=>{
  await withTempTrace(async trace=>{
   for(const key of PARITY_CASE_KEYS){
    const result=await runCorrected(key,trace);
    expect(validateResultSchema(result),JSON.stringify(validateResultSchema.errors)).toBe(true);
   }
  });
 });
 test('attribution blocks deep-equal the golden attribution',async()=>{
  await withTempTrace(async trace=>{
   for(const key of PARITY_CASE_KEYS){
    const result=await runCorrected(key,trace);
    expect(result.attribution).toEqual(loadGolden(key).attribution);
   }
  });
 });
});

describe('native Mastra stream trace',()=>{
 test('trace carries the native workflow chunks verbatim',async()=>{
  await withTempTrace(async trace=>{
   const result=await runCorrected('parallel-partial-failure',trace);
   const chunks=readFileSync(trace,'utf8').trim().split('\n').map(line=>JSON.parse(line) as {type:string;payload:{id?:string;status?:string}});
   const types=[...new Set(chunks.map(c=>c.type))];
   expect(types).toEqual(expect.arrayContaining(['workflow-start','workflow-step-start','workflow-step-result','workflow-finish']));
   for(const id of ['worker.order-details','worker.payment-status','worker.delivery-status','collect','synthesize','finalize']){
    expect(chunks.some(c=>c.payload?.id===id),id).toBe(true);
   }
   expect(result.status).toBe('PARTIAL');
  });
 });
 test('the trace records the failed worker step while the run stays a domain result',async()=>{
  await withTempTrace(async trace=>{
   await runCorrected('parallel-all-failed',trace);
   const chunks=readFileSync(trace,'utf8').trim().split('\n').map(line=>JSON.parse(line) as {type:string;payload:{id?:string;status?:string;output?:{failure_code?:string}}});
   const stepResults=chunks.filter(c=>c.type==='workflow-step-result'&&c.payload?.id?.startsWith('worker.'));
   expect(stepResults).toHaveLength(3);
   expect(stepResults.every(c=>c.payload?.status==='success')).toBe(true);
   expect(stepResults.every(c=>c.payload?.output?.failure_code==='WORKER_EXECUTION_FAILED')).toBe(true);
  });
 });
});
