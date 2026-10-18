import {loadWorkerFixture} from './scenario.js';
import {WorkerExecutionError,type CaseSpec,type WorkerId,type WorkerInput,type WorkerProvider,type WorkerInstructions} from './types.js';
export class ScriptedWorkers implements WorkerProvider {
 private gates=new Map<WorkerId,()=>void>();private entered=new Set<WorkerId>();private cursor=0;private awaitingAck=false;private draining=false;private fixture:WorkerInstructions;
 constructor(private readonly spec:CaseSpec,private readonly orderId:string){this.fixture=loadWorkerFixture(spec.worker_fixture);}
 private pump():void {
  if(this.draining){for(const release of this.gates.values())release();return;}
  const id=this.spec.completion_order[this.cursor];
  if(id===undefined||this.awaitingAck||!this.entered.has(id)||(this.cursor===0&&this.spec.execution_mode==='parallel'&&this.entered.size<2))return;
  this.awaitingAck=true;this.gates.get(id)!();
 }
 async read(id:WorkerId,input:WorkerInput):Promise<unknown>{
  if(this.draining||this.entered.has(id)||input.order_id!==this.orderId)throw new Error('Invalid worker invocation');
  this.entered.add(id);const gate=new Promise<void>(resolve=>this.gates.set(id,resolve));this.pump();await gate;
  const instruction=this.fixture[id];if(instruction.operation==='raise')throw new WorkerExecutionError('Declared worker failure');
  return structuredClone(instruction.output);
 }
 acknowledgeOutcome(id:WorkerId):void {
  if(this.draining)return;
  if(!this.awaitingAck||this.spec.completion_order[this.cursor]!==id)throw new Error('Invalid outcome acknowledgement');
  this.gates.delete(id);this.cursor++;this.awaitingAck=false;this.pump();
 }
 beginDrain():void {this.draining=true;this.pump();}
}
