import {it, expect} from "vitest";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
it("imports and runs all five cases in a fresh process with network denied", () => {
  const script = `
    import net from 'node:net'; import http from 'node:http'; import https from 'node:https';
    import {mkdtemp,rm} from 'node:fs/promises'; import {tmpdir} from 'node:os'; import {join} from 'node:path';
    const blocked=()=>{throw new Error('network denied')};
    net.connect=blocked; net.createConnection=blocked; net.Socket.prototype.connect=blocked;
    http.request=blocked; http.get=blocked; https.request=blocked; https.get=blocked; globalThis.fetch=blocked;
    try {await import('./test/offline-import-probe.ts'); throw new Error('probe guard missing');} catch(e) {if(e.message!=='network denied') throw e;}
    const {runScenarioCase}=await import('./src/runner.ts');
    const {loadScenario}=await import('./src/scenario.ts');
    const dir=await mkdtemp(join(tmpdir(),'br-m2-offline-'));
    try {for(const c of loadScenario().cases) {const r=await runScenarioCase({mode:c.router_mode,caseId:c.id,tracePath:join(dir,c.id+'.jsonl')}); if(r.status!==c.expected_status) throw new Error('wrong outcome');}}
    finally {await rm(dir,{recursive:true,force:true});}
    console.log('offline-passed');
  `;
  expect(execFileSync(process.execPath, ["--import", "tsx", "--input-type=module", "-e", script], {cwd: fileURLToPath(new URL("..", import.meta.url)), encoding: "utf8"}).trim()).toBe("offline-passed");
});
