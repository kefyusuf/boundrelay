import {expect,test} from 'vitest';
import {parseCliOptions,runCli} from '../src/cli.js';
test('strict_cli_rejects_invalid_arguments',()=>{
 const base=['--case','parallel-crash-resume','--trace','trace.jsonl','--state-dir','state'];
 const parsed=parseCliOptions(base);
 expect(parsed.caseId).toBe('parallel-crash-resume');expect(parsed.resume).toBe(false);expect(parsed.replayFrom).toBeUndefined();
 expect(parseCliOptions([...base,'--resume']).resume).toBe(true);
 expect(parseCliOptions([...base,'--replay-from','snap.json']).replayFrom).toBe('snap.json');
 for(const args of [[],base.slice(2),[...base,'--case','other'],[...base,'--unknown','x'],[...base,'positional'],
  ['--case','--trace',...base.slice(2)],[...base,'--resume','value'],[...base,'--resume','--replay-from','snap.json'],
  ['--case','parallel-crash-resume','--trace','trace.jsonl'],['--state-dir','state','--trace','trace.jsonl']])
  expect(()=>parseCliOptions(args)).toThrow();
});
test('tooling_error_has_exit_two_and_no_result',async()=>{
 let stdout='',stderr='';
 const code=await runCli(['--case','unknown-case','--trace','unused.jsonl','--state-dir','state'],v=>{stdout+=v;},v=>{stderr+=v;});
 expect(code).toBe(2);expect(stdout).toBe('');expect(stderr).not.toBe('');
});
