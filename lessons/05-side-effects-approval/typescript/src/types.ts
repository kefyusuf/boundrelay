export const WORKER_IDS=['order-details','payment-status','delivery-status'] as const;
export type WorkerId=typeof WORKER_IDS[number];
export type ExecutionMode='sequential'|'parallel';
export interface WorkerInput {readonly order_id:string}
export type WorkerOutput={order_id:string;order_status:'PROCESSING'|'SHIPPED'|'CANCELLED'}|{order_id:string;payment_status:'PAID'|'UNPAID'}|{order_id:string;delivery_status:'PENDING'|'IN_TRANSIT'|'DELIVERED'|'DELAYED'};
export type WorkerOutcome={worker_id:WorkerId;status:'SUCCEEDED';output:WorkerOutput;failure_code:null}|{worker_id:WorkerId;status:'FAILED';output:null;failure_code:'WORKER_EXECUTION_FAILED'|'INVALID_WORKER_OUTPUT'};
export type CanonicalOutcomes=readonly [WorkerOutcome,WorkerOutcome,WorkerOutcome];
export type ValidationResult<T>={valid:true;value:T}|{valid:false};
export interface Brief {order_id:string;sections:{worker_id:WorkerId;output:WorkerOutput}[];missing_workers:WorkerId[];complete:boolean}
export type ResultStatus='SUCCEEDED'|'PARTIAL'|'FAILED'|'CANCELLED'|'UNKNOWN';
export type ApprovalDecision='granted'|'rejected'|'none';
export type FailureCode='ALL_WORKERS_FAILED'|'APPROVAL_REJECTED'|null;
export type EffectStatus='EFFECT_COMPLETED'|'EFFECT_REJECTED'|'EFFECT_UNPROVABLE'|null;
export interface RunResult {schema_version:'1.0';run_id:string;scenario_id:'order-closure';case_id:string;execution_mode:ExecutionMode;concurrency_limit:number;peak_concurrency:number;order_id:string;status:ResultStatus;worker_outcomes:CanonicalOutcomes;synthesis_invoked:boolean;brief:Brief|null;failure_code:FailureCode;approval_decision:ApprovalDecision;effect_status:EffectStatus;idempotency_key:string|null;reconciled:boolean;trace_path:string;resumed:boolean;restored_cursor:number|null;restored_worker_ids:WorkerId[];state_dir:string;run_state_status:RunStateStatus}
export class WorkerExecutionError extends Error {}
export type StepStatus='PENDING'|'RUNNING'|'SUCCEEDED'|'FAILED'|'CANCELLED';
export type RunStateStatus='RUNNING'|'SUCCEEDED'|'PARTIAL'|'FAILED'|'CANCELLED'|'UNKNOWN';
export interface StepRecord {worker_id:WorkerId;status:StepStatus;output:WorkerOutput|null;failure_code:'WORKER_EXECUTION_FAILED'|'INVALID_WORKER_OUTPUT'|null}
export interface EffectConfirmation {key:string;payload_digest:string;status:'EFFECT_COMPLETED'|'EFFECT_REJECTED';outcome:RefundOutcome|null;duplicate:boolean}
export interface RunStateDocument {state_schema_version:'1.0';run_id:string;scenario_id:'order-closure';case_id:string;execution_mode:ExecutionMode;concurrency_limit:number;requested_order_id:string;status:RunStateStatus;steps:[StepRecord,StepRecord,StepRecord];sequence_cursor:number;digest:string;submit_marker:{key:string;payload_digest:string}|null;effect:EffectConfirmation|null}
export interface StateBinding {case_id:string;execution_mode:ExecutionMode;requested_order_id:string;concurrency_limit:number}
export type StateLoadReason='UNKNOWN_VERSION'|'SCHEMA_INVALID'|'DIGEST_MISMATCH'|'BINDING_MISMATCH'|'TRUNCATED'|'MISSING_SNAPSHOT';
export class StateLoadError extends Error {constructor(public readonly reason:StateLoadReason,detail:string){super(`Run state load failed: ${reason} (${detail})`);this.name='StateLoadError';}}
export type EffectPayload={operation:'cancel-and-refund';order_id:string;refund_amount_cents:4200;currency:'EUR'};
export interface RefundOutcome {refund_id:string;refunded_at:string}
export type EffectOutcome={status:'EFFECT_COMPLETED';outcome:RefundOutcome}|{status:'EFFECT_REJECTED';outcome:null;reason:'INVALID_PAYLOAD'};
export interface LedgerRecord {key:string;payload_digest:string;effect:EffectOutcome}
export type SubmitResult={status:'EFFECT_COMPLETED';outcome:RefundOutcome;reason:null;duplicate:boolean}|{status:'EFFECT_REJECTED';outcome:null;reason:'INVALID_PAYLOAD';duplicate:boolean};
export type LookupResult={status:'EFFECT_COMPLETED';outcome:RefundOutcome}|{status:'EFFECT_REJECTED';outcome:null};
export interface ApprovalMetadata {decision:'granted'|'rejected';approver:string}
export interface ApprovalRecord {operation:'cancel-and-refund';order_id:string;payload_digest:string;decision:'granted'|'rejected';approver:string}
export type AuditRecord={kind:'approval';operation:'cancel-and-refund';order_id:string;payload_digest:string;decision:'granted'|'rejected';approver:string}|{kind:'effect';operation:'cancel-and-refund';order_id:string;idempotency_key:string;effect_status:'EFFECT_COMPLETED'|'EFFECT_REJECTED'|'EFFECT_UNPROVABLE';duplicate:boolean};
export interface RecoveryControls {crash_before_submit?:true;crash_in_submit_window?:true;sink_unavailable?:true}
export interface EffectSink {submit(key:string,digest:string,payload:EffectPayload):SubmitResult;lookup(key:string):LookupResult|null}
export interface ApprovalSink {decide(payload:EffectPayload):{decision:'granted'|'rejected';record:ApprovalRecord}}
export interface AuditSink {append(record:AuditRecord):void}
export interface EventSink {emit(type:string,data:Record<string,unknown>):void}
export interface EffectWiring {ledger:EffectSink;approvalGate:ApprovalSink;audit?:AuditSink|undefined;controls?:RecoveryControls|undefined;on_crash?:(()=>never)|undefined;events?:EventSink|undefined}
export interface WorkerControl {acknowledgeOutcome(id:WorkerId):void;beginDrain():void}
export interface WorkerProvider extends WorkerControl {read(id:WorkerId,input:WorkerInput):Promise<unknown>}
export interface WorkerDefinition {id:WorkerId;handle(input:WorkerInput):Promise<unknown>}
export interface WorkerDirectory {resolve(id:WorkerId):WorkerDefinition|undefined}
export type WorkerLifecycle={kind:'started';worker_id:WorkerId;input:WorkerInput}|{kind:'terminal';outcome:WorkerOutcome};
export type WorkerObserver=(event:WorkerLifecycle)=>void;
export interface StateStore {markRunning(worker:WorkerId):void;recordStepTerminal(worker:WorkerId,outcome:WorkerOutcome):void;markCancelledFrom(worker:WorkerId):void;markTerminal(status:Exclude<RunStateStatus,'RUNNING'>,failureCode?:'ALL_WORKERS_FAILED'|'APPROVAL_REJECTED'):void;markSubmitted(key:string,payloadDigest:string):void;recordEffectOutcome(effect:EffectConfirmation):void;state():RunStateDocument;statePath():string;snapshotPath(seq:number):string}
export interface ExecutorOptions {mode:ExecutionMode;input:WorkerInput;directory:WorkerDirectory;control:WorkerControl;observer:WorkerObserver;store?:StateStore;completion_order?:WorkerId[];queue?:readonly WorkerId[];effect?:EffectWiring}
export interface ExecutionSummary {reads:WorkerOutcome[];effect:EffectConfirmation|null;rejected:boolean;peakConcurrency:number}
export interface CaseSpec {case_id:string;execution_mode:ExecutionMode;worker_fixture:string;completion_order:WorkerId[];approval:ApprovalMetadata;controls?:RecoveryControls;duplicate_key?:boolean}
export interface Scenario {schema_version:'1.0';scenario_id:'order-closure';order_id:string;cases:CaseSpec[]}
export type WorkerInstruction={operation:'return';output:unknown}|{operation:'raise';failure_code:'WORKER_EXECUTION_FAILED'};
export type WorkerInstructions=Record<WorkerId,WorkerInstruction>;



