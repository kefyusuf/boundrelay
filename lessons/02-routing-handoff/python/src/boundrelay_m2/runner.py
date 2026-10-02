from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4
from .scenario import load_scenario, find_scenario_case, load_failure_fixtures
from .scripted_router import classify_with_code, ScriptedRouteProvider
from .policy import apply_confidence_policy
from .receivers import create_receiver_directory
from .schemas import validate_route_decision, validate_handoff, validate_run_result
from .trace import MemoryEventSink, write_jsonl
from .types import RouterMode, RouteDecisionProvider, ReceiverDirectory, HandoffResult, RouteDecision, RouteSelection, ReceiverInput, FailureCode


async def run_scenario_case(
    *, mode: RouterMode, case_id: str, trace_path: str,
    route_provider: RouteDecisionProvider | None = None,
    receiver_directory: ReceiverDirectory | None = None,
    clock: Callable[[], datetime] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> HandoffResult:
    case = find_scenario_case(load_scenario(), case_id)
    if case.router_mode != mode: raise ValueError('Requested mode does not match canonical case mode')
    next_id = id_factory or (lambda: str(uuid4()))
    run_id = next_id()
    sink = MemoryEventSink(run_id=run_id,source='python',clock=clock,id_factory=next_id)
    selection: RouteSelection | None = None

    def finish(failure: FailureCode | None) -> HandoffResult:
        fields = {'proposed_route': selection.proposed_route if selection else None, 'selected_route': selection.selected_route if selection else None, 'receiver': selection.receiver if selection else None, 'fallback_applied': selection.fallback_applied if selection else False, 'specialist_invoked': failure is None}
        result = HandoffResult(schema_version='1.0',run_id=run_id,scenario_id='support-handoff',case_id=case.id,router_mode=mode,status='FAILED' if failure else 'SUCCEEDED',**fields,failure_code=failure,trace_path=trace_path)
        validation = validate_run_result(result.to_dict())
        if not validation.ok: raise ValueError('Invalid result: '+'; '.join(validation.errors))
        sink.emit('run.failed' if failure else 'run.completed', {'status': result.status, **fields, **({'failure_code':failure} if failure else {})})
        write_jsonl(trace_path,sink.events)
        return result

    sink.emit('run.created',{'scenario_id':'support-handoff','case_id':case.id,'router_mode':mode})
    sink.emit('run.started',{'case_id':case.id,'router_mode':mode})
    if mode == 'code': raw = asdict(classify_with_code(case.request))
    else:
        provider = route_provider or ScriptedRouteProvider.from_file()
        sink.emit('model.requested',{'case_id':case.id})
        raw = await provider.next_decision(case_id=case.id,request=case.request)
        sink.emit('model.completed',{'case_id':case.id,'decision':raw})
    validation = validate_route_decision(raw)
    if not validation.ok:
        sink.emit('route.rejected',{'router_mode':mode,'failure_code':'INVALID_ROUTE_DECISION'})
        return finish('INVALID_ROUTE_DECISION')
    selection = apply_confidence_policy(RouteDecision(**validation.value))
    sink.emit('route.selected',{'router_mode':mode,'proposed_route':selection.proposed_route,'selected_route':selection.selected_route,'confidence':selection.confidence,'fallback_applied':selection.fallback_applied})
    failure = load_failure_fixtures()[case.failure_ref] if case.failure_ref else {}
    receiver_input = {'ticket_id':case.ticket_id,'request_text':case.request}
    for field in failure.get('omit_receiver_input_fields',[]): receiver_input.pop(field)
    candidate = {'schema_version':'1.0','handoff_id':next_id(),'sender':'support-router','receiver':selection.receiver,'sender_intent':{'route':selection.proposed_route,'confidence':selection.confidence,'policy_outcome':selection.policy_outcome},'receiver_input':receiver_input}
    sink.emit('handoff.requested',{k:v for k,v in candidate.items() if k != 'schema_version'})

    def reject(code: FailureCode):
        sink.emit('handoff.rejected',{'handoff_id':candidate['handoff_id'],'receiver':candidate['receiver'],'failure_code':code})
        return finish(code)

    handoff = validate_handoff(candidate)
    if not handoff.ok: return reject('HANDOFF_CONTEXT_INVALID')
    directory = receiver_directory or create_receiver_directory(tuple(failure.get('unavailable_receivers',())))
    receiver = directory.resolve(handoff.value['receiver'])
    if receiver is None: return reject('HANDOFF_RECEIVER_UNAVAILABLE')
    sink.emit('handoff.accepted',{'handoff_id':candidate['handoff_id'],'receiver':candidate['receiver']})
    await receiver.handle(ReceiverInput(**handoff.value['receiver_input']))
    return finish(None)
