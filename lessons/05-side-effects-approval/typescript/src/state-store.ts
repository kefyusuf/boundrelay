import {randomUUID} from 'node:crypto';
import {existsSync,mkdirSync,readdirSync,readFileSync,renameSync,rmSync,writeFileSync} from 'node:fs';
import {basename,dirname,join} from 'node:path';
import {WORKER_IDS,StateLoadError,type EffectConfirmation,type RunStateDocument,type RunStateStatus,type StateBinding,type StepRecord,type WorkerId,type WorkerOutcome,type WorkerOutput} from './types.js';
import {canonicalJson,canonicalStateBody,stateDigest,validateRunStateDocument} from './schemas.js';
const TERMINAL=new Set(['SUCCEEDED','FAILED']);
export class StateStore {
 private readonly document:RunStateDocument;
 constructor(private readonly root:string,private readonly binding:StateBinding,queue:readonly WorkerId[],runId:string=randomUUID(),seed?:RunStateDocument){
  this.document=seed===undefined?{state_schema_version:'1.0',run_id:runId,scenario_id:'order-closure',case_id:binding.case_id,execution_mode:binding.execution_mode,concurrency_limit:binding.concurrency_limit,requested_order_id:binding.requested_order_id,status:'RUNNING',steps:queue.map(id=>({worker_id:id,status:'PENDING',output:null,failure_code:null})) as [StepRecord,StepRecord,StepRecord],sequence_cursor:0,digest:'',submit_marker:null,effect:null}:{...structuredClone(seed),status:'RUNNING'};
  mkdirSync(dirname(this.statePath()),{recursive:true});mkdirSync(dirname(this.snapshotPath(1)),{recursive:true});
  this.flush();
 }
 static create(root:string,binding:StateBinding,queue:readonly WorkerId[]):StateStore {return new StateStore(root,binding,queue);}
 static resume(document:RunStateDocument,statePath:string):StateStore {
  const dir=dirname(statePath),root=basename(dir)===document.run_id?dirname(dir):dir;
  return new StateStore(root,{case_id:document.case_id,execution_mode:document.execution_mode,requested_order_id:document.requested_order_id,concurrency_limit:document.concurrency_limit},[],document.run_id,document);
 }
 state():RunStateDocument {return structuredClone(this.document);}
 statePath():string {return join(this.root,this.document.run_id,'state.json');}
 snapshotPath(seq:number):string {return join(this.root,this.document.run_id,'checkpoints',`step-${seq}.json`);}
 markRunning(worker:WorkerId):void {this.step(worker).status='RUNNING';this.flush();}
 recordStepTerminal(worker:WorkerId,outcome:WorkerOutcome):void {
  const step=this.step(worker);
  if(outcome.status==='SUCCEEDED'){step.status='SUCCEEDED';step.output=structuredClone(outcome.output) as WorkerOutput;step.failure_code=null;}
  else{step.status='FAILED';step.output=null;step.failure_code=outcome.failure_code;}
  this.flush(WORKER_IDS.indexOf(worker)+1);
 }
 markCancelledFrom(worker:WorkerId):void {
  const from=WORKER_IDS.indexOf(worker);
  for(const step of this.document.steps)if(WORKER_IDS.indexOf(step.worker_id)>=from&&!TERMINAL.has(step.status))step.status='CANCELLED';
  this.flush();
 }
 markTerminal(status:Exclude<RunStateStatus,'RUNNING'>,failureCode?:'ALL_WORKERS_FAILED'|'APPROVAL_REJECTED'):void {
  if(status==='FAILED'&&failureCode!=='ALL_WORKERS_FAILED'&&failureCode!=='APPROVAL_REJECTED')throw new Error('Invalid terminal failure code');
  this.document.status=status;this.flush();
 }
 markSubmitted(key:string,payloadDigest:string):void {
  this.document.submit_marker={key,payload_digest:payloadDigest};
  this.flush();
 }
 recordEffectOutcome(effect:EffectConfirmation):void {
  this.document.effect=structuredClone(effect);
  this.flush();
 }
 private step(worker:WorkerId):StepRecord {return this.document.steps[WORKER_IDS.indexOf(worker)]!;}
 private flush(snapshotSeq?:number):void {
  this.document.sequence_cursor=this.document.steps.filter(s=>TERMINAL.has(s.status)).length;
  this.document.digest=stateDigest(canonicalStateBody(this.document));
  if(!validateRunStateDocument(this.document).valid)throw new Error('Invalid run state document');
  const content=canonicalJson(this.document);
  this.writeAtomic(this.statePath(),content);
  if(snapshotSeq!==undefined)this.writeAtomic(this.snapshotPath(snapshotSeq),content);
 }
 private writeAtomic(path:string,content:string):void {
  const tmp=path+'.tmp';
  try{writeFileSync(tmp,content,'utf8');renameSync(tmp,path);}catch(error){rmSync(tmp,{force:true});throw error;}
 }
}
export function loadRunStateDocument(path:string,expectedBinding:StateBinding):RunStateDocument {
 let raw:unknown;
 try{raw=JSON.parse(readFileSync(path,'utf8'));}catch{throw new StateLoadError('TRUNCATED','run state document is not valid JSON');}
 if(raw===null||typeof raw!=='object'||Array.isArray(raw)||(raw as Record<string,unknown>).state_schema_version!=='1.0')throw new StateLoadError('UNKNOWN_VERSION','missing or unsupported state_schema_version');
 const validation=validateRunStateDocument(raw);
 if(!validation.valid)throw new StateLoadError('SCHEMA_INVALID','run state document failed the closed schema');
 const document=validation.value;
 if(document.digest!==stateDigest(canonicalStateBody(document)))throw new StateLoadError('DIGEST_MISMATCH',`run_id=${document.run_id} case_id=${document.case_id}`);
 if(document.case_id!==expectedBinding.case_id||document.execution_mode!==expectedBinding.execution_mode||document.requested_order_id!==expectedBinding.requested_order_id||document.concurrency_limit!==expectedBinding.concurrency_limit)throw new StateLoadError('BINDING_MISMATCH',`run_id=${document.run_id} case_id=${document.case_id}`);
 return document;
}
export function loadRunState(stateRoot:string,expectedBinding:StateBinding):{document:RunStateDocument;restored_from:string} {
 const flat=join(stateRoot,'state.json');
 const paths:string[]=existsSync(flat)?[flat]:readdirSync(stateRoot).filter(name=>existsSync(join(stateRoot,name,'state.json'))).map(name=>join(stateRoot,name,'state.json')).sort();
 if(paths.length!==1)throw new Error(`Expected exactly one run state document under ${stateRoot}, found ${paths.length}`);
 const path=paths[0]!;
 const document=loadRunStateDocument(path,expectedBinding);
 document.steps.forEach((step,index)=>{if(TERMINAL.has(step.status))verifySnapshot(join(stateRoot,document.run_id,'checkpoints',`step-${index+1}.json`),index+1,document.run_id);});
 return {document,restored_from:path};
}
function verifySnapshot(path:string,seq:number,runId:string):void {
 const missing=(detail:string)=>new StateLoadError('MISSING_SNAPSHOT',`checkpoint step-${seq} for run_id=${runId}: ${detail}`);
 if(!existsSync(path))throw missing('missing');
 let snapshot:unknown;
 try{snapshot=JSON.parse(readFileSync(path,'utf8'));}catch{throw missing('unreadable');}
 if(snapshot===null||typeof snapshot!=='object'||Array.isArray(snapshot)||(snapshot as Record<string,unknown>).state_schema_version!=='1.0')throw missing('invalid');
 const validation=validateRunStateDocument(snapshot);
 if(!validation.valid||validation.value.digest!==stateDigest(canonicalStateBody(validation.value)))throw missing('invalid');
}



