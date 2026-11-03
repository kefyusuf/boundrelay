import asyncio
import re
from .approval import require_approval
from .idempotency import effect_digest,effect_key
from .schemas import validate_worker_output
from .types import (WORKER_IDS,WorkerExecutionError,WorkerInput,ExecutorOptions,
    ExecutionSummary,WorkerId)

class CrashSignal(Exception):
    pass

def _effect_payload(order_id:str)->dict[str,object]:
    return {'operation':'cancel-and-refund','order_id':order_id,'refund_amount_cents':4200,'currency':'EUR'}

async def execute_workers(options:ExecutorOptions)->ExecutionSummary:
    mode,input,directory,control,observer=options.mode,options.input,options.directory,options.control,options.observer
    store=options.store;wiring=options.effect
    if mode not in ('sequential','parallel') or type(input) is not WorkerInput or type(input.order_id) is not str or re.fullmatch(r'ORD-[0-9]{4}',input.order_id) is None:raise ValueError('Invalid execution input')
    queue=WORKER_IDS if options.queue is None else options.queue
    expected=[worker_id for worker_id in WORKER_IDS if worker_id in queue]
    if len(set(queue))!=len(queue) or len(queue)!=len(expected) or any(worker_id!=expected[index] for index,worker_id in enumerate(queue)):raise ValueError('Invalid execution queue')
    limit=1 if mode=='sequential' else 2;pending=list(queue);active={};reads=[];peak=0;fatal=[]
    async def invoke(worker_id):
        try:
            worker=directory.resolve(worker_id)
            if worker is None or worker.id!=worker_id:raise ValueError('Unknown worker')
            isolated=WorkerInput(input.order_id);observer({'kind':'started','worker_id':worker_id,'input':isolated})
            try:
                validation=validate_worker_output(worker_id,await worker.handle(isolated),input.order_id)
                return {'worker_id':worker_id,'status':'SUCCEEDED' if validation.valid else 'FAILED',
                        'output':validation.value,'failure_code':None if validation.valid else 'INVALID_WORKER_OUTPUT'}
            except WorkerExecutionError:
                return {'worker_id':worker_id,'status':'FAILED','output':None,'failure_code':'WORKER_EXECUTION_FAILED'}
        except Exception as error:
            if not fatal:fatal.append(error)
            raise
    try:
        while pending or active:
            while not fatal and pending and len(active)<limit:
                worker_id=pending.pop(0)
                if store is not None:store.mark_running(worker_id)
                active[worker_id]=asyncio.create_task(invoke(worker_id));peak=max(peak,len(active))
            if fatal:raise fatal[0]
            done,_=await asyncio.wait(active.values(),return_when=asyncio.FIRST_COMPLETED)
            if fatal:raise fatal[0]
            for task in done:
                outcome=task.result();worker_id=outcome['worker_id'];del active[worker_id]
                if store is not None:store.record_step_terminal(worker_id,outcome)
                reads.append(outcome);observer({'kind':'terminal','outcome':outcome});control.acknowledge_outcome(worker_id)
        if wiring is None or store is None or any(outcome['status']!='SUCCEEDED' for outcome in reads):
            return ExecutionSummary(reads=reads,peak_concurrency=peak,effect=None,rejected=False)
        payload=_effect_payload(input.order_id);key=effect_key(payload);digest=effect_digest(payload)
        events=wiring.events
        if events is not None:events.emit('approval.requested',{'operation':'cancel-and-refund','order_id':input.order_id,'payload_digest':digest})
        decision_record=wiring.approval_gate.decide(payload)
        record=decision_record['record']
        if events is not None:events.emit('approval.granted' if decision_record['decision']=='granted' else 'approval.rejected',{'operation':'cancel-and-refund','order_id':input.order_id,'payload_digest':digest})
        if wiring.audit is not None:
            wiring.audit.append({'kind':'approval',**record})
        if decision_record['decision']!='granted':
            return ExecutionSummary(reads=reads,peak_concurrency=peak,effect=None,rejected=True)
        require_approval(record,payload)
        controls=wiring.controls or {}
        if controls.get('crash_before_submit') is True:
            if wiring.on_crash is None:raise ValueError('Crash control requires on_crash')
            wiring.on_crash()
        store.mark_submitted(key,digest)
        if events is not None:events.emit('tool.requested',{'key':key,'payload_digest':digest,'side_effect_class':'external'})
        try:submitted=wiring.ledger.submit(key,digest,payload)
        except Exception:
            if events is not None:events.emit('tool.failed',{'key':key})
            raise
        if controls.get('crash_in_submit_window') is True:
            if wiring.on_crash is None:raise ValueError('Crash control requires on_crash')
            wiring.on_crash()
        effect={'key':key,'payload_digest':digest,'status':submitted['status'],
                'outcome':submitted['outcome'],'duplicate':submitted['duplicate']}
        if events is not None:events.emit('tool.completed',{'key':key,'status':submitted['status'],'duplicate':submitted['duplicate']})
        store.record_effect_outcome(effect)
        if wiring.audit is not None:
            wiring.audit.append({'kind':'effect','operation':'cancel-and-refund','order_id':input.order_id,'idempotency_key':key,'effect_status':submitted['status'],'duplicate':submitted['duplicate']})
        return ExecutionSummary(reads=reads,peak_concurrency=peak,effect=effect,rejected=False)
    except CrashSignal:
        raise
    except Exception:
        control.begin_drain();await asyncio.gather(*active.values(),return_exceptions=True)
        raise


