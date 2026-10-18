import {expect,test} from 'vitest';import {execFileSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
test('fresh_import_guard_and_all_six_offline_runs',()=>{
 const cwd=fileURLToPath(new URL('..',import.meta.url));
 const report=JSON.parse(execFileSync(process.execPath,['--import','tsx','test/helpers/offline-runner.ts'],{cwd,encoding:'utf8',timeout:15000}));
 expect(report).toEqual({import_probe_blocked:true,statuses:['SUCCEEDED','SUCCEEDED','SUCCEEDED','PARTIAL','FAILED','PARTIAL']});
});
