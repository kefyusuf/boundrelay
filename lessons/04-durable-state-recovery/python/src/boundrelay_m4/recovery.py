from copy import deepcopy
from dataclasses import dataclass
from .collector import canonicalize_outcomes
from .executor import execute_workers
from .scenario import load_scenario
from .schemas import validate_run_result
from .state_store import StateStore,load_run_state,load_run_state_document
from .synthesizer import synthesize_brief
from .types import WORKER_IDS,Brief,CanonicalOutcomes,CaseSpec,ExecutorOptions,RunResult,RunStateDocument,StateBinding,WorkerId,WorkerInput,WorkerOutcome

RECORDING=('SUCCEEDED','FAILED')

@dataclass(frozen=True)
class RunOptions:
    case_id:str
    trace_path:str
    state_dir:str
    resume:bool=False
    replay_from:str|None=None
    sink:object=None
    directory:object=None
    control:object=None
    synthesizer:object=None
    state_store:object=None
    observer:object=None
    on_crash:object=None

def recorded_worker_ids(document:RunStateDocument)->list[WorkerId]:
    return [step['worker_id'] for step in document['steps'] if step['status'] in RECORDING]

def recorded_outcomes(document:RunStateDocument)->list[WorkerOutcome]:
    return [deepcopy({'worker_id':step['worker_id'],'status':step['status'],'output':step['output'],'failure_code':step['failure_code']}) for step in document['steps'] if step['status'] in RECORDING]

def derive_pending(document:RunStateDocument)->list[WorkerId]:
    statuses={step['worker_id']:step['status'] for step in document['steps']}
    return [worker_id for worker_id in WORKER_IDS if statuses[worker_id] in ('PENDING','RUNNING','CANCELLED')]

def _resolve_case(case_id:str)->tuple[CaseSpec,StateBinding]:
    scenario=load_scenario()
    spec=next((entry for entry in scenario.cases if entry.case_id==case_id),None)
    if spec is None:raise ValueError('Unknown case')
    return spec,StateBinding(case_id=spec.case_id,execution_mode=spec.execution_mode,requested_order_id=scenario.order_id,concurrency_limit=1 if spec.execution_mode=='sequential' else 2)

def _require_resumable(document:RunStateDocument)->None:
    if document['status'] not in ('RUNNING','CANCELLED'):raise ValueError(f"Run state is not resumable (run_id={document['run_id']} status={document['status']})")

def _emit_restored(sink,binding:StateBinding,document:RunStateDocument)->None:
    if sink is None:return
    sink.emit('checkpoint.restored',{'case_id':binding.case_id,'execution_mode':binding.execution_mode,'requested_order_id':binding.requested_order_id,'concurrency_limit':binding.concurrency_limit,'state_status':document['status'],'restored_cursor':document['sequence_cursor'],'restored_worker_ids':recorded_worker_ids(document)})

def _emit_checkpoint_saved(sink,binding:StateBinding,store,worker_id:WorkerId)->None:
    if sink is None:return
    document=store.state()
    sink.emit('checkpoint.saved',{'case_id':binding.case_id,'execution_mode':binding.execution_mode,'requested_order_id':binding.requested_order_id,'concurrency_limit':binding.concurrency_limit,'step_name':worker_id,'state_status':document['status'],'sequence_cursor':document['sequence_cursor']})

async def _complete_recovered_run(store,options,binding:StateBinding,document:RunStateDocument)->RunResult:
    if (options.directory is None)!=(options.control is None):raise ValueError('Override pair required')
    base=options.observer
    def observe(event):
        if base is not None:base(event)
        if event['kind']=='terminal':_emit_checkpoint_saved(options.sink,binding,store,event['outcome']['worker_id'])
    summary=await execute_workers(ExecutorOptions(binding.execution_mode,WorkerInput(binding.requested_order_id),options.directory,options.control,observe,store=store,queue=tuple(derive_pending(document))))
    restored={outcome['worker_id']:outcome for outcome in recorded_outcomes(document)}
    fresh={outcome['worker_id']:outcome for outcome in summary.outcomes}
    canonical=canonicalize_outcomes([restored.get(worker_id,fresh.get(worker_id)) for worker_id in WORKER_IDS],binding.requested_order_id)
    succeeded=sum(1 for outcome in canonical if outcome['status']=='SUCCEEDED')
    status='SUCCEEDED' if succeeded==3 else 'FAILED' if succeeded==0 else 'PARTIAL'
    failure_code='ALL_WORKERS_FAILED' if status=='FAILED' else None
    brief=None;synthesis_invoked=False
    if succeeded>0:
        if options.sink is not None:options.sink.emit('step.started',{'step_name':'synthesize','worker_outcomes':list(canonical)})
        synthesizer=options.synthesizer if options.synthesizer is not None else synthesize_brief
        brief=synthesizer(binding.requested_order_id,canonical);synthesis_invoked=True
        if options.sink is not None:options.sink.emit('step.completed',{'step_name':'synthesize','brief':brief})
    if failure_code is not None:store.mark_terminal(status,failure_code)
    else:store.mark_terminal(status)
    result={'schema_version':'1.0','run_id':store.state()['run_id'],'scenario_id':'order-brief-recovery','case_id':binding.case_id,'execution_mode':binding.execution_mode,'concurrency_limit':binding.concurrency_limit,'peak_concurrency':max(summary.peak_concurrency,1),'order_id':binding.requested_order_id,'status':status,'worker_outcomes':list(canonical),'synthesis_invoked':synthesis_invoked,'brief':brief,'failure_code':failure_code,'trace_path':options.trace_path,'resumed':True,'restored_cursor':document['sequence_cursor'],'restored_worker_ids':recorded_worker_ids(document),'state_dir':options.state_dir,'run_state_status':status}
    if not validate_run_result(result):raise ValueError('Invalid recovery result')
    return result

async def resume_run(options)->RunResult:
    _,binding=_resolve_case(options.case_id)
    loaded=load_run_state(options.state_dir,binding)
    document:RunStateDocument=loaded['document']
    _require_resumable(document)
    _emit_restored(options.sink,binding,document)
    store=options.state_store if options.state_store is not None else StateStore.resume(document,loaded['restored_from'])
    return await _complete_recovered_run(store,options,binding,document)

async def replay_from(snapshot_path,options)->RunResult:
    _,binding=_resolve_case(options.case_id)
    document=load_run_state_document(snapshot_path,binding)
    _require_resumable(document)
    _emit_restored(options.sink,binding,document)
    if options.state_store is not None:
        store=options.state_store
    else:
        store=StateStore.create(options.state_dir,binding,WORKER_IDS)
        for outcome in recorded_outcomes(document):store.record_step_terminal(outcome['worker_id'],outcome)
    return await _complete_recovered_run(store,options,binding,store.state())
