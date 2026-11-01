import {expect,test} from 'vitest';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
test('fresh_import_guard_and_all_six_offline_runs',()=>{
 const cwd=fileURLToPath(new URL('..',import.meta.url));
 const report=JSON.parse(execFileSync(process.execPath,['--import','tsx','test/helpers/offline-runner.ts'],{cwd,encoding:'utf8',timeout:60000})) as {import_probe_blocked:boolean;statuses:string[]};
 expect(report).toEqual({import_probe_blocked:true,statuses:['SUCCEEDED','CRASHED','CRASHED','CANCELLED','SUCCEEDED','SUCCEEDED']});
});
