from uuid import uuid4
from .scenario import load_scenario
from .scripted_workers import ScriptedWorkers
from .workers import create_worker_directory
from .executor import execute_workers
from .collector import canonicalize_outcomes
from .synthesizer import synthesize_brief
from .trace import TraceSink
from .schemas import validate_run_result
from .types import WorkerInput,ExecutorOptions,RunResult

async def run_case(*,case_id,trace_path,mode=None,directory=None,control=None,synthesizer=None)->RunResult:
    scenario=load_scenario();spec=next((c for c in scenario.cases if c.case_id==case_id),None)
    if spec is None or not trace_path or (mode is not None and mode!=spec.execution_mode):raise ValueError('Unknown case or incompatible mode')
    if (directory is None)!=(control is None):raise ValueError('Directory and control must be supplied together')
    provider=ScriptedWorkers(spec,scenario.order_id);run_id=str(uuid4());sink=TraceSink(run_id,trace_path)
    context={'scenario_id':'order-brief','case_id':spec.case_id,'execution_mode':spec.execution_mode,'order_id':scenario.order_id,'concurrency_limit':1 if spec.execution_mode=='sequential' else 2}
    def observe(event):
        if event['kind']=='started':sink.emit('step.started',{'step_name':'worker.'+event['worker_id'],'worker_id':event['worker_id'],'order_id':event['input'].order_id})
        else:
            outcome=event['outcome'];sink.emit('step.completed' if outcome['status']=='SUCCEEDED' else 'step.failed',{'step_name':'worker.'+outcome['worker_id'],'outcome':outcome})
    try:
        sink.emit('run.created',context);sink.emit('run.started',context)
        execution=await execute_workers(ExecutorOptions(spec.execution_mode,WorkerInput(scenario.order_id),directory or create_worker_directory(provider),control or provider,observe))
        outcomes=canonicalize_outcomes(execution.outcomes,scenario.order_id);successes=sum(o['status']=='SUCCEEDED' for o in outcomes)
        if successes:sink.emit('step.started',{'step_name':'synthesize','worker_outcomes':list(outcomes)})
        brief=(synthesizer or synthesize_brief)(scenario.order_id,outcomes) if successes else None
        result={'schema_version':'1.0','run_id':run_id,**context,'peak_concurrency':execution.peak_concurrency,'status':'SUCCEEDED' if successes==3 else 'PARTIAL' if successes else 'FAILED','worker_outcomes':list(outcomes),'synthesis_invoked':bool(successes),'brief':brief,'failure_code':None if successes else 'ALL_WORKERS_FAILED','trace_path':trace_path}
        if not validate_run_result(result):raise ValueError('Invalid run result')
        if successes:sink.emit('step.completed',{'step_name':'synthesize','brief':brief})
        sink.emit('run.completed' if successes else 'run.failed',{key:result[key] for key in ('status','worker_outcomes','synthesis_invoked','brief','failure_code','peak_concurrency')})
        return result
    finally:sink.flush()
