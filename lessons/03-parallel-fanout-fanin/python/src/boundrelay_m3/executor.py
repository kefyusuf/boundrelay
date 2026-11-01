import asyncio
import re
from .types import WORKER_IDS,WorkerInput,WorkerExecutionError,ExecutorOptions,ExecutionSummary
from .schemas import validate_worker_output

async def execute_workers(options:ExecutorOptions)->ExecutionSummary:
    mode,input,directory,control,observer=options.mode,options.input,options.directory,options.control,options.observer
    if mode not in ('sequential','parallel') or type(input) is not WorkerInput or type(input.order_id) is not str or re.fullmatch(r'ORD-[0-9]{4}',input.order_id) is None:raise ValueError('Invalid execution input')
    limit=1 if mode=='sequential' else 2;pending=list(WORKER_IDS);active={};outcomes=[];peak=0;fatal=[]
    async def invoke(worker_id):
        try:
            worker=directory.resolve(worker_id)
            if worker is None or worker.id!=worker_id:raise ValueError('Unknown worker')
            isolated=WorkerInput(input.order_id);observer({'kind':'started','worker_id':worker_id,'input':isolated})
            try:
                validation=validate_worker_output(worker_id,await worker.handle(isolated),input.order_id)
                outcome={'worker_id':worker_id,'status':'SUCCEEDED' if validation.valid else 'FAILED',
                         'output':validation.value,'failure_code':None if validation.valid else 'INVALID_WORKER_OUTPUT'}
            except WorkerExecutionError:
                outcome={'worker_id':worker_id,'status':'FAILED','output':None,'failure_code':'WORKER_EXECUTION_FAILED'}
            observer({'kind':'terminal','outcome':outcome});return outcome
        except Exception as error:
            if not fatal:fatal.append(error)
            raise
    try:
        while pending or active:
            while not fatal and pending and len(active)<limit:
                worker_id=pending.pop(0);active[worker_id]=asyncio.create_task(invoke(worker_id));peak=max(peak,len(active))
            if fatal:raise fatal[0]
            done,_=await asyncio.wait(active.values(),return_when=asyncio.FIRST_COMPLETED)
            if fatal:raise fatal[0]
            for task in done:
                outcome=task.result();worker_id=outcome['worker_id'];outcomes.append(outcome)
                control.acknowledge_outcome(worker_id);del active[worker_id]
        return ExecutionSummary(outcomes,peak)
    except Exception:
        control.begin_drain();await asyncio.gather(*active.values(),return_exceptions=True)
        raise
