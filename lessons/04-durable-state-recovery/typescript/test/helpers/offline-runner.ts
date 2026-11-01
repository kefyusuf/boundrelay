import net from 'node:net';import http from 'node:http';import https from 'node:https';
import {mkdtempSync,rmSync} from 'node:fs';import {join} from 'node:path';import {tmpdir} from 'node:os';
const blocked=():never=>{throw new Error('network denied');};
net.connect=blocked;net.createConnection=blocked;net.Socket.prototype.connect=blocked;
http.request=blocked;http.get=blocked;https.request=blocked;https.get=blocked;globalThis.fetch=blocked;
try{await import('../offline-import-probe.js');throw new Error('Import guard missing');}catch(error){if(!(error instanceof Error)||error.message!=='network denied')throw error;}
const {runCase}=await import('../../src/runner.js'),{CrashSignal}=await import('../../src/executor.js'),{loadScenario}=await import('../../src/scenario.js');
const dir=mkdtempSync(join(tmpdir(),'br-m5-offline-'));const statuses:string[]=[];
const crash=():never=>{throw new CrashSignal('crash');};
try{
 for(const c of loadScenario().cases){
  try{statuses.push((await runCase({caseId:c.case_id,tracePath:join(dir,c.case_id+'.jsonl'),stateDir:join(dir,c.case_id),on_crash:crash})).status);}
  catch(error){if(!(error instanceof CrashSignal))throw error;statuses.push('CRASHED');}
 }
}finally{rmSync(dir,{recursive:true,force:true});}
console.log(JSON.stringify({import_probe_blocked:true,statuses}));
