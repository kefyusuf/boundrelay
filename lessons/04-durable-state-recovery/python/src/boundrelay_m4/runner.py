import os
from .scenario import load_scenario
from .scripted_workers import ScriptedWorkers
from .workers import create_worker_directory
from .executor import execute_workers
from .collector import canonicalize_outcomes
from .synthesizer import synthesize_brief
from .trace import TraceSink
from .schemas import validate_run_result
from .state_store import StateStore,load_run_state,load_run_state_document
from .recovery import RunOptions,resume_run,replay_from as replay_from_snapshot,recorded_outcomes,derive_pending
from .attribution import build_attribution,worker_records,restored_running
from .types import WORKER_IDS,CaseSpec,ExecutorOptions,RunResult,StateBinding,WorkerInput

def _context(binding:StateBinding,state_dir:str)->dict:
    return {'scenario_id':'order-brief-recovery','case_id':binding.case_id,'execution_mode':binding.execution_mode,'order_id':binding.requested_order_id,'concurrency_limit':binding.concurrency_limit,'state_dir':state_dir}

def _step_observer(sink):
    def observe(event):
        if event['kind']=='started':sink.emit('step.started',{'step_name':'worker.'+event['worker_id'],'worker_id':event['worker_id'],'order_id':event['input'].order_id})
        else:
            outcome=event['outcome'];sink.emit('step.completed' if outcome['status']=='SUCCEEDED' else 'step.failed',{'step_name':'worker.'+outcome['worker_id'],'outcome':outcome})
    return observe

def _observer(sink,binding:StateBinding,store):
    step=_step_observer(sink)
    def observe(event):
        step(event)
        if event['kind']=='terminal':
            document=store.state()
            sink.emit('checkpoint.saved',{'case_id':binding.case_id,'execution_mode':binding.execution_mode,'requested_order_id':binding.requested_order_id,'concurrency_limit':binding.concurrency_limit,'step_name':event['outcome']['worker_id'],'state_status':document['status'],'sequence_cursor':document['sequence_cursor']})
    return observe

def _assemble(options,binding:StateBinding,run_id,peak,status,outcomes,synthesis_invoked,brief,failure_code,attribution)->RunResult:
    return {'schema_version':'1.0','run_id':run_id,'scenario_id':'order-brief-recovery','case_id':binding.case_id,'execution_mode':binding.execution_mode,'concurrency_limit':binding.concurrency_limit,'peak_concurrency':max(peak,1),'order_id':binding.requested_order_id,'status':status,'worker_outcomes':list(outcomes),'synthesis_invoked':synthesis_invoked,'brief':brief,'failure_code':failure_code,'trace_path':options.trace_path,'resumed':False,'restored_cursor':None,'restored_worker_ids':[],'state_dir':options.state_dir,'run_state_status':status,'attribution':attribution}

def _attributed(tables,outcomes,synthesis_invoked,restored_running=()):
    records=worker_records(outcomes,restored_running)+([('synthesize',1)] if synthesis_invoked else [])
    return build_attribution(records,tables['price_table'],tables['latency_ms'])

async def _fresh_run(options,binding:StateBinding,spec,store,sink,tables)->RunResult:
    provider=ScriptedWorkers(spec,binding.requested_order_id) if options.directory is None else None
    def on_crash():
        sink.flush();os._exit(2)
    execution=await execute_workers(ExecutorOptions(spec.execution_mode,WorkerInput(binding.requested_order_id),options.directory or create_worker_directory(provider),options.control or provider,_observer(sink,binding,store),store=store,controls=spec.controls,completion_order=spec.completion_order,on_crash=options.on_crash or on_crash))
    if execution.cancelled_before is not None:
        store.mark_cancelled_from(execution.cancelled_before)
        sink.emit('run.cancelled',{'case_id':binding.case_id,'execution_mode':binding.execution_mode,'requested_order_id':binding.requested_order_id,'concurrency_limit':binding.concurrency_limit,'cancelled_before':execution.cancelled_before,'code':'CANCELLED_BEFORE_STEP'})
        store.mark_terminal('CANCELLED')
        result=_assemble(options,binding,store.state()['run_id'],execution.peak_concurrency,'CANCELLED',recorded_outcomes(store.state()),False,None,None,_attributed(tables,recorded_outcomes(store.state()),False))
        if not validate_run_result(result):raise ValueError('Invalid run result')
        return result
    outcomes=canonicalize_outcomes(execution.outcomes,binding.requested_order_id);successes=sum(o['status']=='SUCCEEDED' for o in outcomes)
    if successes:sink.emit('step.started',{'step_name':'synthesize','worker_outcomes':list(outcomes)})
    brief=(options.synthesizer or synthesize_brief)(binding.requested_order_id,outcomes) if successes else None
    if successes:sink.emit('step.completed',{'step_name':'synthesize','brief':brief})
    status='SUCCEEDED' if successes==3 else 'PARTIAL' if successes else 'FAILED';failure_code=None if successes else 'ALL_WORKERS_FAILED'
    if failure_code is None:store.mark_terminal(status)
    else:store.mark_terminal(status,failure_code)
    result=_assemble(options,binding,store.state()['run_id'],execution.peak_concurrency,status,outcomes,bool(successes),brief,failure_code,_attributed(tables,outcomes,bool(successes)))
    if not validate_run_result(result):raise ValueError('Invalid run result')
    return result

async def run_case(*,case_id,trace_path,state_dir,resume=False,replay_from=None,sink=None,directory=None,control=None,synthesizer=None,state_store=None,on_crash=None)->RunResult:
    scenario=load_scenario();spec=next((c for c in scenario.cases if c.case_id==case_id),None)
    if spec is None or not trace_path or not state_dir:raise ValueError('Unknown case or missing options')
    tables=scenario.attribution
    if tables is None:raise ValueError('Scenario is missing attribution tables')
    if (directory is None)!=(control is None):raise ValueError('Directory and control must be supplied together')
    if resume and replay_from is not None:raise ValueError('Resume and replay are mutually exclusive')
    binding=StateBinding(case_id=spec.case_id,execution_mode=spec.execution_mode,requested_order_id=scenario.order_id,concurrency_limit=1 if spec.execution_mode=='sequential' else 2)
    context=_context(binding,state_dir)
    loaded=load_run_state(state_dir,binding) if resume else None
    replay_document=load_run_state_document(replay_from,binding) if replay_from is not None else None
    pending=derive_pending(loaded['document']) if loaded is not None else (derive_pending(replay_document) if replay_document is not None else [])
    resume_spec=CaseSpec(spec.case_id,'sequential' if len(pending)<2 else spec.execution_mode,spec.worker_fixture,tuple(worker_id for worker_id in spec.completion_order if worker_id in pending))
    if loaded is not None:run_id=loaded['document']['run_id']
    else:
        store=state_store if state_store is not None else StateStore.create(state_dir,binding,WORKER_IDS)
        if state_store is None and replay_document is not None:
            for outcome in recorded_outcomes(replay_document):store.record_step_terminal(outcome['worker_id'],outcome)
        run_id=store.state()['run_id']
    sink=sink if sink is not None else TraceSink(run_id,trace_path)
    try:
        sink.emit('run.created',context);sink.emit('run.started',context)
        provider=ScriptedWorkers(resume_spec,binding.requested_order_id) if directory is None else None
        resolved_directory=directory or create_worker_directory(provider);resolved_control=control or provider
        if loaded is not None:
            options=RunOptions(case_id=case_id,trace_path=trace_path,state_dir=state_dir,resume=True,sink=sink,directory=resolved_directory,control=resolved_control,synthesizer=synthesizer,state_store=None,observer=_step_observer(sink))
            result=await resume_run(options)
        elif replay_from is not None:
            options=RunOptions(case_id=case_id,trace_path=trace_path,state_dir=state_dir,replay_from=replay_from,sink=sink,directory=resolved_directory,control=resolved_control,synthesizer=synthesizer,state_store=store,observer=_step_observer(sink))
            result=await replay_from_snapshot(replay_from,options)
        else:
            options=RunOptions(case_id=case_id,trace_path=trace_path,state_dir=state_dir,sink=sink,directory=directory,control=control,synthesizer=synthesizer,state_store=store,on_crash=on_crash)
            result=await _fresh_run(options,binding,spec,store,sink,tables)
        if result['status']!='CANCELLED':
            terminal='run.failed' if result['status']=='FAILED' else 'run.completed'
            sink.emit(terminal,{key:result[key] for key in ('status','worker_outcomes','synthesis_invoked','brief','failure_code','peak_concurrency')})
        return result
    finally:sink.flush()
