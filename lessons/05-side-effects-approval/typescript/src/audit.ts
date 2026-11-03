import {appendFileSync,existsSync,mkdirSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {canonicalJson,validateAuditRecord} from './schemas.js';
import type {AuditRecord} from './types.js';
export class AuditWriter {
 constructor(private readonly stateDir:string){mkdirSync(stateDir,{recursive:true});}
 path():string {return join(this.stateDir,'audit.jsonl');}
 append(record:AuditRecord):void {
  if(!validateAuditRecord(record))throw new Error('Invalid audit record');
  appendFileSync(this.path(),canonicalJson(record)+'\n','utf8');
 }
 records():AuditRecord[] {
  if(!existsSync(this.path()))return [];
  return readFileSync(this.path(),'utf8').split('\n').filter(line=>line.trim()!=='').map(line=>JSON.parse(line) as AuditRecord);
 }
}
