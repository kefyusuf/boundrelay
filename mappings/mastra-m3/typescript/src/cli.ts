/** P5c mapping CLI: --case <id> [--mode corrected|naive] --trace <file>.
 *
 * Prints exactly one JSON result line on stdout and exits 0 for every
 * domain result (SUCCEEDED, PARTIAL, FAILED). Tooling failures - unknown
 * or missing options, unknown case, naive-mode default propagation -
 * print to stderr and exit 2 without a canonical result.
 */
import {pathToFileURL} from 'node:url';
import {resolve as resolvePath} from 'node:path';
import {runCorrected} from './mapping.js';
import {runNaive} from './naive.js';

export type CliOptions={mode:'corrected'|'naive';case_id:string;trace_path:string};
const OPTION_NAMES=['--mode','--case','--trace'] as const;
const VALID_MODES=['corrected','naive'] as const;
const DEFAULT_MODE='corrected' as const;

export function parseCliOptions(args:readonly string[]):CliOptions{
 const values=new Map<string,string>();
 for(let index=0;index<args.length;index+=2){
  const name=args[index];
  const value=args[index+1];
  if(name===undefined||!(OPTION_NAMES as readonly string[]).includes(name)||values.has(name)||value===undefined||value.startsWith('--'))throw new Error('Invalid CLI arguments');
  values.set(name,value);
 }
 if(!values.has('--case')||!values.has('--trace'))throw new Error('Missing --case or --trace');
 const rawMode=values.get('--mode')??DEFAULT_MODE;
 if(!(VALID_MODES as readonly string[]).includes(rawMode))throw new Error(`Invalid mode: ${rawMode}`);
 return {mode:rawMode as 'corrected'|'naive',case_id:values.get('--case') as string,trace_path:values.get('--trace') as string};
}

export async function runCli(args:readonly string[],stdout:(text:string) => void=text => process.stdout.write(text),stderr:(text:string) => void=text => process.stderr.write(text)):Promise<number>{
 try{
  const options=parseCliOptions(args);
  const result=options.mode==='naive'?await runNaive(options.case_id,options.trace_path):await runCorrected(options.case_id,options.trace_path);
  stdout(`${JSON.stringify(result)}\n`);
  return 0;
 }catch(error){
  stderr(`${error instanceof Error?error.message:'Tooling failure'}\n`);
  return 2;
 }
}

const entry=process.argv[1];
if(entry!==undefined&&import.meta.url===pathToFileURL(resolvePath(entry)).href)void runCli(process.argv.slice(2)).then(code=>{process.exitCode=code;});
