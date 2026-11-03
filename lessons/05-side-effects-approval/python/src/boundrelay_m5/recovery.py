from dataclasses import dataclass
from .idempotency import effect_digest,effect_key
from .state_store import StateStore,load_run_state
from .types import (EffectConfirmation,EffectPayload,RecoveryControls,StateBinding,
    WorkerOutcome)

class RecoveryError(Exception):
    pass

@dataclass(frozen=True)
class RecoveryOptions:
    state_root:str
    binding:StateBinding
    ledger:object
    audit:object=None
    controls:RecoveryControls|None=None

@dataclass(frozen=True)
class RecoveryResult:
    status:str
    reconciled:bool
    effect:EffectConfirmation|None
    idempotency_key:str|None
    reads:list[WorkerOutcome]

def _effect_payload(order_id:str)->EffectPayload:
    return {'operation':'cancel-and-refund','order_id':order_id,'refund_amount_cents':4200,'currency':'EUR'}

def _recorded_reads(document:dict[str,object])->list[WorkerOutcome]:
    from copy import deepcopy
    return [deepcopy({'worker_id':step['worker_id'],'status':step['status'],'output':step['output'],'failure_code':step['failure_code']}) for step in document['steps'] if step['status'] in ('SUCCEEDED','FAILED')]
def resume_run(options:RecoveryOptions)->RecoveryResult:
    loaded=load_run_state(options.state_root,options.binding)
    document=loaded['document']
    if document['status']!='RUNNING':raise RecoveryError(f"Run state is not resumable (run_id={document['run_id']} status={document['status']})")
    store=StateStore.resume(document,loaded['restored_from'])
    reads=_recorded_reads(document)
    payload=_effect_payload(options.binding.requested_order_id)
    key=effect_key(payload)
    if document['effect'] is not None:
        store.mark_terminal('SUCCEEDED')
        return RecoveryResult('SUCCEEDED',False,document['effect'],document['effect']['key'],reads)
    marker=document['submit_marker']
    if marker is None:raise RecoveryError(f"Run state has no effect decision to resolve (run_id={document['run_id']})")
    if marker['key']!=key or marker['payload_digest']!=effect_digest(payload):raise RecoveryError(f"Effect binding mismatch (run_id={document['run_id']})")
    if options.controls is not None and options.controls.get('sink_unavailable') is True:
        store.mark_terminal('UNKNOWN')
        return RecoveryResult('UNKNOWN',False,None,key,reads)
    found=options.ledger.lookup(key)
    if found is not None:
        adopted={'key':key,'payload_digest':marker['payload_digest'],'status':found['status'],'outcome':found['outcome'],'duplicate':False}
        store.record_effect_outcome(adopted)
        if options.audit is not None:
            options.audit.append({'kind':'effect','operation':'cancel-and-refund','order_id':options.binding.requested_order_id,'idempotency_key':key,'effect_status':found['status'],'duplicate':False})
        store.mark_terminal('SUCCEEDED')
        return RecoveryResult('SUCCEEDED',True,adopted,key,reads)
    submitted=options.ledger.submit(key,marker['payload_digest'],payload)
    effect={'key':key,'payload_digest':marker['payload_digest'],'status':submitted['status'],'outcome':submitted['outcome'],'duplicate':submitted['duplicate']}
    store.record_effect_outcome(effect)
    if options.audit is not None:
        options.audit.append({'kind':'effect','operation':'cancel-and-refund','order_id':options.binding.requested_order_id,'idempotency_key':key,'effect_status':submitted['status'],'duplicate':submitted['duplicate']})
    store.mark_terminal('SUCCEEDED')
    return RecoveryResult('SUCCEEDED',False,effect,key,reads)

