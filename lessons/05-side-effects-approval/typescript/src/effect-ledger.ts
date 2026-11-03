import {existsSync,mkdirSync,readFileSync,renameSync,rmSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {validateEffectPayload,validateEffectRecord} from './schemas.js';
import type {EffectOutcome,EffectPayload,LedgerRecord,LookupResult,SubmitResult} from './types.js';
const REFUND_ID='RFL-1001',REFUNDED_AT='2026-11-02T00:00:00Z';
type LedgerFile={records:LedgerRecord[]};
function resultOf(effect:EffectOutcome,duplicate:boolean):SubmitResult {
 return effect.status==='EFFECT_COMPLETED'
  ?{status:'EFFECT_COMPLETED',outcome:effect.outcome,reason:null,duplicate}
  :{status:'EFFECT_REJECTED',outcome:null,reason:'INVALID_PAYLOAD',duplicate};
}
export class EffectLedger {
 constructor(private readonly stateDir:string){mkdirSync(stateDir,{recursive:true});}
 path():string {return join(this.stateDir,'effect-ledger.json');}
 private load():LedgerFile {
  if(!existsSync(this.path()))return {records:[]};
  let raw:unknown;
  try{raw=JSON.parse(readFileSync(this.path(),'utf8'));}catch{throw new Error('Effect ledger is not valid JSON');}
  if(raw===null||typeof raw!=='object'||Array.isArray(raw)||!Array.isArray((raw as LedgerFile).records)
   ||!(raw as LedgerFile).records.every(record=>validateEffectRecord(record).valid))throw new Error('Effect ledger failed the closed schema');
  return raw as LedgerFile;
 }
 private writeAtomic(content:string):void {
  const tmp=this.path()+'.tmp';
  try{writeFileSync(tmp,content,'utf8');renameSync(tmp,this.path());}catch(error){rmSync(tmp,{force:true});throw error;}
 }
 submit(key:string,digest:string,payload:EffectPayload):SubmitResult {
  const data=this.load();
  const existing=data.records.find(record=>record.key===key);
  if(existing)return resultOf(existing.effect,true);
  const effect:EffectOutcome=validateEffectPayload(payload).valid
   ?{status:'EFFECT_COMPLETED',outcome:{refund_id:REFUND_ID,refunded_at:REFUNDED_AT}}
   :{status:'EFFECT_REJECTED',outcome:null,reason:'INVALID_PAYLOAD'};
  const record:LedgerRecord={key,payload_digest:digest,effect};
  this.writeAtomic(JSON.stringify({...data,records:[...data.records,record]}));
  return resultOf(effect,false);
 }
 lookup(key:string):LookupResult|null {
  const found=this.load().records.find(record=>record.key===key);
  if(!found)return null;
  return found.effect.status==='EFFECT_COMPLETED'?{status:'EFFECT_COMPLETED',outcome:found.effect.outcome}:{status:'EFFECT_REJECTED',outcome:null};
 }
 records():LedgerRecord[] {return structuredClone(this.load().records);}
}

