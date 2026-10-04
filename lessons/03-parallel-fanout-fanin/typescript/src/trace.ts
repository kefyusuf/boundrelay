import {randomUUID} from 'node:crypto';import {mkdirSync,writeFileSync} from 'node:fs';import {dirname} from 'node:path';
import {finiteJson,eventValidator} from './schemas.js';
export interface RunEvent {schema_version:'1.0';event_id:string;run_id:string;sequence:number;type:string;timestamp:string;source:'typescript';data:Record<string,unknown>}
export class TraceSink {
 private events:RunEvent[]=[];
 constructor(private readonly runId:string,private readonly path:string){}
 emit(type:string,data:Record<string,unknown>):void {
  if(!finiteJson(data))throw new Error('Unsafe event data');
  const event:RunEvent={schema_version:'1.0',event_id:randomUUID(),run_id:this.runId,sequence:this.events.length+1,type,timestamp:new Date().toISOString(),source:'typescript',data:structuredClone(data)};
  if(!eventValidator(event))throw new Error('Invalid event envelope');this.events.push(event);
 }
 flush():void {mkdirSync(dirname(this.path),{recursive:true});writeFileSync(this.path,this.events.map(e=>JSON.stringify(e)).join('\n')+'\n','utf8');}
}
