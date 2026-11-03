import os
from copy import deepcopy
from .approval import ApprovalGate
from .audit import AuditWriter
from .effect_ledger import EffectLedger
from .executor import execute_workers
from .recovery import RecoveryOptions,resume_run
from .scenario import load_scenario
from .schemas import validate_run_result
from .scripted_workers import ScriptedWorkers
from .state_store import StateStore,load_run_state
from .trace import TraceSink
from .types import (WORKER_IDS,CaseSpec,EffectWiring,ExecutorOptions,RunResult,
    RunStateDocument,StateBinding,WorkerInput,WorkerOutcome)
from .workers import create_worker_directory

TERMINAL_READ=('SUCCEEDED','FAILED')

def _recorded_reads(document:RunStateDocument)->list[WorkerOutcome]:
    return [deepcopy({'worker_id':step['worker_id'],'status':step['status'],'output':step['output'],'failure_code':step['failure_code']}) for step in document['steps'] if step['status'] in TERMINAL_READ]

def _step_observer(sink):
    def observe(event):
        if event['kind']=='started':sink.emit('step.started',{'step_name':'worker.'+event['worker_id'],'worker_id':event['worker_id'],'order_id':event['input'].order_id})
        else:
            outcome=event['outcome'];sink.emit('step.completed' if outcome['status']=='SUCCEEDED' else 'step.failed',{'step_name':'worker.'+outcome['worker_id'],'outcome':outcome})
    return observe

def _observer(sink,binding:StateBinding,store,extra=None):
    step=_step_observer(sink)
    def observe(event):
        if extra is not None:extra(event)
        step(event)
        if event['kind']=='terminal':
            document=store.state()
            sink.emit('checkpoint.saved',{'case_id':binding.case_id,'execution_mode':binding.execution_mode,'requested_order_id':binding.requested_order_id,'concurrency_limit':binding.concurrency_limit,'step_name':event['outcome']['worker_id'],'state_status':document['status'],'sequence_cursor':document['sequence_cursor']})
    return observe

def _crash(sink):
    def on_crash():
        sink.flush();os._exit(2)
    return on_crash

def _effect_wiring(options,spec,sink,controls=None):
    return EffectWiring(ledger=EffectLedger(options['state_dir']),approval_gate=ApprovalGate(spec.approval),audit=AuditWriter(options['state_dir']),controls=controls,on_crash=options.get('on_crash') or _crash(sink),events=sink)
def _assemble(options,binding:StateBinding,run_id,peak,status,reads,decision,effect,effect_status,key,failure_code,reconciled,resumed,restored_cursor,restored_worker_ids)->RunResult:
    canonical=[next((outcome for outcome in reads if outcome['worker_id']==worker_id),None) for worker_id in WORKER_IDS]
    return {'schema_version':'1.0','run_id':run_id,'scenario_id':'order-closure','case_id':binding.case_id,'execution_mode':binding.execution_mode,'concurrency_limit':binding.concurrency_limit,'peak_concurrency':max(peak,1),'order_id':binding.requested_order_id,'status':status,'worker_outcomes':canonical,'synthesis_invoked':False,'brief':None,'failure_code':failure_code,'approval_decision':decision,'effect_status':effect_status,'idempotency_key':key,'reconciled':reconciled,'trace_path':options['trace_path'],'resumed':resumed,'restored_cursor':restored_cursor,'restored_worker_ids':restored_worker_ids,'state_dir':options['state_dir'],'run_state_status':status}

def _publish(sink,result:RunResult)->RunResult:
    if not validate_run_result(result):raise ValueError('Invalid run result')
    sink.emit('run.failed' if result['status']=='FAILED' else 'run.completed',{'status':result['status'],'worker_outcomes':result['worker_outcomes'],'synthesis_invoked':False,'brief':None,'failure_code':result['failure_code'],'peak_concurrency':result['peak_concurrency'],'reconciled':result['reconciled'],'approval_decision':result['approval_decision'],'effect_status':result['effect_status'],'idempotency_key':result['idempotency_key']})
    return result

def _finish(store,sink,status,failure_code,result:RunResult)->RunResult:
    if status=='FAILED':store.mark_terminal('FAILED',failure_code or 'ALL_WORKERS_FAILED')
    else:store.mark_terminal(status)
    return _publish(sink,result)

async def _fresh_run(options,binding:StateBinding,spec,store,sink)->RunResult:
    provider=ScriptedWorkers(spec,binding.requested_order_id) if options.get('directory') is None else None
    execution=await execute_workers(ExecutorOptions(spec.execution_mode,WorkerInput(binding.requested_order_id),options.get('directory') or create_worker_directory(provider),options.get('control') or provider,_observer(sink,binding,store,options.get('observer')),store=store,completion_order=spec.completion_order,effect=_effect_wiring(options,spec,sink,spec.controls)))
    reads=execution.reads;successes=sum(outcome['status']=='SUCCEEDED' for outcome in reads)
    effect=execution.effect;effect_status=execution.effect['status'] if execution.effect is not None else None
    key=execution.effect['key'] if execution.effect is not None else None
    if successes==3 and execution.rejected:
        status,decision,effect,effect_status,key,failure_code='FAILED','rejected',None,None,None,'APPROVAL_REJECTED'
    elif successes==3:
        status,decision,failure_code='SUCCEEDED','granted',None
    elif successes:
        status,decision,effect,effect_status,key,failure_code='PARTIAL','none',None,None,None,None
    else:
        status,decision,effect,effect_status,key,failure_code='FAILED','none',None,None,None,'ALL_WORKERS_FAILED'
    return _finish(store,sink,status,failure_code,_assemble(options,binding,store.state()['run_id'],execution.peak_concurrency,status,reads,decision,effect,effect_status,key,failure_code,False,False,None,[]))
async def _resumed_run(options,binding:StateBinding,spec,loaded,sink)->RunResult:
    document=loaded['document']
    resumed_store=StateStore.resume(document,loaded['restored_from'])
    statuses={step['worker_id']:step['status'] for step in document['steps']}
    pending=[worker_id for worker_id in WORKER_IDS if statuses[worker_id] in ('PENDING','RUNNING','CANCELLED')]
    peak=1
    if pending:
        resume_spec=CaseSpec(spec.case_id,spec.execution_mode if len(pending)>1 else 'sequential',spec.worker_fixture,tuple(worker_id for worker_id in spec.completion_order if worker_id in pending),spec.approval)
        provider=ScriptedWorkers(resume_spec,binding.requested_order_id) if options.get('directory') is None else None
        execution=await execute_workers(ExecutorOptions(resume_spec.execution_mode,WorkerInput(binding.requested_order_id),options.get('directory') or create_worker_directory(provider),options.get('control') or provider,_observer(sink,binding,resumed_store,options.get('observer')),store=resumed_store,queue=pending,completion_order=resume_spec.completion_order))
        peak=max(execution.peak_concurrency,1)
    restored_cursor=document['sequence_cursor']
    restored_worker_ids=[step['worker_id'] for step in document['steps'] if step['status'] in TERMINAL_READ]
    current=resumed_store.state();reads=_recorded_reads(current);successes=sum(outcome['status']=='SUCCEEDED' for outcome in reads)
    if current['effect'] is not None or current['submit_marker'] is not None:
        controls={'sink_unavailable':True} if spec.controls is not None and spec.controls.get('sink_unavailable') is True else None
        recovery=resume_run(RecoveryOptions(state_root=options['state_dir'],binding=binding,ledger=EffectLedger(options['state_dir']),audit=AuditWriter(options['state_dir']),controls=controls))
        status='UNKNOWN' if recovery.status=='UNKNOWN' else 'SUCCEEDED'
        effect_status='EFFECT_UNPROVABLE' if status=='UNKNOWN' else (recovery.effect['status'] if recovery.effect is not None else None)
        result=_assemble(options,binding,resumed_store.state()['run_id'],peak,status,reads,'granted',recovery.effect,effect_status,recovery.idempotency_key,None,recovery.reconciled,True,restored_cursor,restored_worker_ids)
        return _publish(sink,result)
    if successes==3:
        provider=ScriptedWorkers(spec,binding.requested_order_id)
        execution=await execute_workers(ExecutorOptions('sequential',WorkerInput(binding.requested_order_id),create_worker_directory(provider),provider,_step_observer(sink),store=resumed_store,queue=[],completion_order=spec.completion_order,effect=_effect_wiring(options,spec,sink)))
        effect=execution.effect
        result=_assemble(options,binding,resumed_store.state()['run_id'],max(execution.peak_concurrency,1),'SUCCEEDED',reads,'granted',effect,'EFFECT_COMPLETED',effect['key'],None,False,True,restored_cursor,restored_worker_ids)
        return _finish(resumed_store,sink,'SUCCEEDED',None,result)
    status,failure_code=('PARTIAL',None) if successes else ('FAILED','ALL_WORKERS_FAILED')
    return _finish(resumed_store,sink,status,failure_code,_assemble(options,binding,resumed_store.state()['run_id'],peak,status,reads,'none',None,None,None,failure_code,False,True,restored_cursor,restored_worker_ids))
async def run_case(*,case_id,trace_path,state_dir,resume=False,sink=None,directory=None,control=None,state_store=None,observer=None,on_crash=None)->RunResult:
    scenario=load_scenario();spec=next((c for c in scenario.cases if c.case_id==case_id),None)
    if spec is None or not trace_path or not state_dir:raise ValueError('Unknown case or missing options')
    if (directory is None)!=(control is None):raise ValueError('Directory and control must be supplied together')
    binding=StateBinding(case_id=spec.case_id,execution_mode=spec.execution_mode,requested_order_id=scenario.order_id,concurrency_limit=1 if spec.execution_mode=='sequential' else 2)
    context={'scenario_id':'order-closure','case_id':spec.case_id,'execution_mode':spec.execution_mode,'order_id':scenario.order_id,'concurrency_limit':binding.concurrency_limit,'state_dir':state_dir}
    options={'trace_path':trace_path,'state_dir':state_dir,'directory':directory,'control':control,'observer':observer,'on_crash':on_crash}
    loaded=load_run_state(state_dir,binding) if resume else None
    if loaded is not None:run_id=loaded['document']['run_id'];store=None
    else:
        store=state_store if state_store is not None else StateStore.create(state_dir,binding,WORKER_IDS)
        run_id=store.state()['run_id']
    sink=sink if sink is not None else TraceSink(run_id,trace_path)
    try:
        sink.emit('run.created',context);sink.emit('run.started',context)
        result=await (_resumed_run(options,binding,spec,loaded,sink) if loaded is not None else _fresh_run(options,binding,spec,store,sink))
        return result
    finally:sink.flush()



