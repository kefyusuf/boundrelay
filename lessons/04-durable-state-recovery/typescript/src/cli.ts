import {resolve} from 'node:path';import {pathToFileURL} from 'node:url';
import {runCase,type RunOptions} from './runner.js';
export function parseCliOptions(args:string[]):RunOptions {
 const values=new Map<string,string>(),flags=new Set<string>(),required=['--case','--trace','--state-dir'],known=[...required,'--replay-from','--resume'];
 for(let index=0;index<args.length;){
  const name=args[index++]!;
  if(!known.includes(name)||values.has(name)||flags.has(name))throw new Error('Invalid CLI arguments');
  if(name==='--resume'){flags.add(name);continue;}
  const value=args[index++];
  if(value===undefined||!value||value.startsWith('--'))throw new Error('Invalid CLI arguments');
  values.set(name,value);
 }
 if(required.some(name=>!values.get(name)))throw new Error('Missing CLI option');
 if(flags.has('--resume')&&values.has('--replay-from'))throw new Error('Resume and replay are mutually exclusive');
 const options:RunOptions={caseId:values.get('--case')!,tracePath:values.get('--trace')!,stateDir:values.get('--state-dir')!,resume:flags.has('--resume')};
 const replay=values.get('--replay-from');
 if(replay!==undefined)options.replayFrom=replay;
 return options;
}
export async function runCli(args:string[],stdout:(text:string)=>void=text=>process.stdout.write(text),stderr:(text:string)=>void=text=>process.stderr.write(text)):Promise<number>{
 try{stdout(JSON.stringify(await runCase(parseCliOptions(args)))+'\n');return 0;}catch(error){stderr((error instanceof Error?error.message:'Tooling failure')+'\n');return 2;}
}
const entry=process.argv[1];if(entry!==undefined&&import.meta.url===pathToFileURL(resolve(entry)).href)void runCli(process.argv.slice(2)).then(code=>{process.exitCode=code;});
