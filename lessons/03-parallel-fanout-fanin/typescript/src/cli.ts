import {resolve} from 'node:path';import {pathToFileURL} from 'node:url';
import {runCase,type RunOptions} from './runner.js';
export function parseCliOptions(args:string[]):RunOptions {
 const values=new Map<string,string>(),names=['--mode','--case','--trace'];
 for(let i=0;i<args.length;i+=2){const name=args[i],value=args[i+1];if(name===undefined||!names.includes(name)||values.has(name)||value===undefined||value.startsWith('--'))throw new Error('Invalid CLI arguments');values.set(name,value);}
 if(names.some(n=>!values.get(n)))throw new Error('Missing CLI option');
 const mode=values.get('--mode');if(mode!=='sequential'&&mode!=='parallel')throw new Error('Invalid mode');
 return {mode,caseId:values.get('--case')!,tracePath:values.get('--trace')!};
}
export async function runCli(args:string[],stdout:(text:string)=>void=text=>process.stdout.write(text),stderr:(text:string)=>void=text=>process.stderr.write(text)):Promise<number>{
 try{stdout(JSON.stringify(await runCase(parseCliOptions(args)))+'\n');return 0;}catch(error){stderr((error instanceof Error?error.message:'Tooling failure')+'\n');return 2;}
}
const entry=process.argv[1];if(entry!==undefined&&import.meta.url===pathToFileURL(resolve(entry)).href)void runCli(process.argv.slice(2)).then(code=>{process.exitCode=code;});
