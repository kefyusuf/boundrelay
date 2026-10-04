import {expect,test} from 'vitest';import {parseCliOptions,runCli} from '../src/cli.js';
test('strict_cli_rejects_invalid_arguments',()=>{
 const base=['--mode','parallel','--case','parallel-complete','--trace','trace.jsonl'];expect(parseCliOptions(base).mode).toBe('parallel');
 for(const args of [[],base.slice(2),[...base,'--case','other'],[...base,'--unknown','x'],[...base,'positional'],['--mode','other',...base.slice(2)],['--mode','--case',...base.slice(2)]])expect(()=>parseCliOptions(args)).toThrow();
});
test('tooling_error_has_exit_two_and_no_result',async()=>{
 let stdout='',stderr='';const code=await runCli(['--mode','sequential','--case','parallel-complete','--trace','unused.jsonl'],v=>stdout+=v,v=>stderr+=v);
 expect(code).toBe(2);expect(stdout).toBe('');expect(stderr).not.toBe('');
});
