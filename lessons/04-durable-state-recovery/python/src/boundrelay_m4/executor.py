import asyncio
import re
from .types import WORKER_IDS,WorkerInput,WorkerExecutionError,ExecutorOptions,ExecutionSummary,WorkerId
from .schemas import validate_worker_output

class CrashSignal(Exception):
    pass

def _crash_boundary_ready(store,crash_after:WorkerId)->bool:
    document=store.state();steps=document['steps'];step=steps[WORKER_IDS.index(crash_after)]
    recorded=sum(1 for entry in steps if entry['status'] in ('SUCCEEDED','FAILED'))
    return document['status']=='RUNNING' and step['status'] in ('SUCCEEDED','FAILED') and document['sequence_cursor']==recorded

async def execute_workers(options:ExecutorOptions)->ExecutionSummary:
    mode,input,directory,control,observer=options.mode,options.input,options.directory,options.control,options.observer
    store=options.store;controls=options.controls;on_crash=options.on_crash
    if mode not in ('sequential','parallel') or type(input) is not WorkerInput or type(input.order_id) is not str or re.fullmatch(r'ORD-[0-9]{4}',input.order_id) is None:raise ValueError('Invalid execution input')
    queue=WORKER_IDS if options.queue is None else options.queue
    expected=[worker_id for worker_id in WORKER_IDS if worker_id in queue]
    if len(set(queue))!=len(queue) or len(queue)!=len(expected) or any(worker_id!=expected[index] for index,worker_id in enumerate(queue)):raise ValueError('Invalid execution queue')
    crash_after=controls.crash_after if controls is not None else None
    cancel_before=controls.cancel_before if controls is not None else None
    if crash_after is not None and cancel_before is not None:raise ValueError('At most one control is allowed')
    if crash_after is not None and (store is None or on_crash is None):raise ValueError('Crash control requires store and on_crash')
    crash_pos=None if crash_after is None else WORKER_IDS.index(crash_after)+1
    limit=1 if mode=='sequential' else 2;pending=list(queue);active={};outcomes=[];peak=0;fatal=[];cancel_fired=False
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
            return outcome
        except Exception as error:
            if not fatal:fatal.append(error)
            raise
    try:
        while pending or active:
            while not fatal and not cancel_fired and pending and len(active)<limit:
                worker_id=pending[0]
                if cancel_before is not None and worker_id==cancel_before:cancel_fired=True;break
                if crash_pos is not None and WORKER_IDS.index(worker_id)>=crash_pos:break
                pending.pop(0)
                if store is not None:store.mark_running(worker_id)
                active[worker_id]=asyncio.create_task(invoke(worker_id));peak=max(peak,len(active))
            if fatal:raise fatal[0]
            if cancel_fired and not active:break
            done,_=await asyncio.wait(active.values(),return_when=asyncio.FIRST_COMPLETED)
            if fatal:raise fatal[0]
            for task in done:
                outcome=task.result();worker_id=outcome['worker_id'];del active[worker_id]
                if store is not None:store.record_step_terminal(worker_id,outcome)
                if crash_after is not None and not active and _crash_boundary_ready(store,crash_after):on_crash()
                outcomes.append(outcome);observer({'kind':'terminal','outcome':outcome});control.acknowledge_outcome(worker_id)
        if cancel_fired:return ExecutionSummary(outcomes,peak,cancel_before)
        return ExecutionSummary(outcomes,peak)
    except CrashSignal:
        raise
    except Exception:
        control.begin_drain();await asyncio.gather(*active.values(),return_exceptions=True)
        raise
