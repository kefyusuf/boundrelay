export const WORKER_IDS=['order-details','payment-status','delivery-status'] as const;
export type WorkerId=typeof WORKER_IDS[number];
export type ExecutionMode='sequential'|'parallel';
export interface WorkerInput {readonly order_id:string}
export type WorkerOutput={order_id:string;order_status:'PROCESSING'|'SHIPPED'|'CANCELLED'}|{order_id:string;payment_status:'PAID'|'UNPAID'}|{order_id:string;delivery_status:'PENDING'|'IN_TRANSIT'|'DELIVERED'|'DELAYED'};
export type WorkerOutcome={worker_id:WorkerId;status:'SUCCEEDED';output:WorkerOutput;failure_code:null}|{worker_id:WorkerId;status:'FAILED';output:null;failure_code:'WORKER_EXECUTION_FAILED'|'INVALID_WORKER_OUTPUT'};
export type CanonicalOutcomes=readonly [WorkerOutcome,WorkerOutcome,WorkerOutcome];
export type ValidationResult<T>={valid:true;value:T}|{valid:false};
export interface Brief {order_id:string;sections:{worker_id:WorkerId;output:WorkerOutput}[];missing_workers:WorkerId[];complete:boolean}
export interface RunResult {schema_version:'1.0';run_id:string;scenario_id:'order-brief';case_id:string;execution_mode:ExecutionMode;concurrency_limit:number;peak_concurrency:number;order_id:string;status:'SUCCEEDED'|'PARTIAL'|'FAILED';worker_outcomes:CanonicalOutcomes;synthesis_invoked:boolean;brief:Brief|null;failure_code:'ALL_WORKERS_FAILED'|null;trace_path:string}
export class WorkerExecutionError extends Error {}
export interface WorkerControl {acknowledgeOutcome(id:WorkerId):void;beginDrain():void}
export interface WorkerProvider extends WorkerControl {read(id:WorkerId,input:WorkerInput):Promise<unknown>}
export interface WorkerDefinition {id:WorkerId;handle(input:WorkerInput):Promise<unknown>}
export interface WorkerDirectory {resolve(id:WorkerId):WorkerDefinition|undefined}
export type WorkerLifecycle={kind:'started';worker_id:WorkerId;input:WorkerInput}|{kind:'terminal';outcome:WorkerOutcome};
export type WorkerObserver=(event:WorkerLifecycle)=>void;
export interface ExecutorOptions {mode:ExecutionMode;input:WorkerInput;directory:WorkerDirectory;control:WorkerControl;observer:WorkerObserver}
export interface ExecutionSummary {outcomes:WorkerOutcome[];peakConcurrency:number}
export interface CaseSpec {case_id:string;execution_mode:ExecutionMode;worker_fixture:string;completion_order:WorkerId[]}
export interface Scenario {schema_version:'1.0';scenario_id:'order-brief';order_id:string;cases:CaseSpec[]}
export type WorkerInstruction={operation:'return';output:unknown}|{operation:'raise';failure_code:'WORKER_EXECUTION_FAILED'};
export type WorkerInstructions=Record<WorkerId,WorkerInstruction>;
