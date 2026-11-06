import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import {mkdtempSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';

// Fail-closed offline harness: every network constructor explodes before
// any mapping or framework module is imported. If the Mastra workflow
// engine (or anything it loads) attempts a connection, the run dies with
// 'network denied' instead of passing.
const blocked=():never=>{throw new Error('network denied');};
net.connect=blocked as typeof net.connect;
net.createConnection=blocked as typeof net.createConnection;
net.Socket.prototype.connect=blocked as typeof net.Socket.prototype.connect;
http.request=blocked as typeof http.request;
http.get=blocked as typeof http.get;
https.request=blocked as typeof https.request;
https.get=blocked as typeof https.get;
(globalThis as {fetch:unknown}).fetch=blocked;

try{
 await import('../offline-import-probe.js');
 throw new Error('Import guard missing');
}catch(error){
 if(!(error instanceof Error)||error.message!=='network denied')throw error;
}
const {runCorrected}=await import('../../src/mapping.js');
const {loadScenario}=await import('../../src/fixtures.js');
const dir=mkdtempSync(join(tmpdir(),'br-mastra-m3-offline-'));
const statuses:string[]=[];
const peaks:number[]=[];
try{
 for(const spec of loadScenario().cases){
  const result=await runCorrected(spec.case_id,join(dir,`${spec.case_id}.jsonl`));
  statuses.push(result.status);
  peaks.push(result.peak_concurrency);
 }
}finally{
 rmSync(dir,{recursive:true,force:true});
}
console.log(JSON.stringify({import_probe_blocked:true,statuses,peaks}));
