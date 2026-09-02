from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from .bounded_router import RejectedRoute, route_decision
from .deterministic_router import classify_deterministically
from .fake_decision_provider import ScriptedDecisionProvider
from .scenario import find_scenario_case, load_scenario
from .schemas import validate_run_result
from .specialists import RecordingSpecialistDispatcher
from .trace import MemoryEventSink, write_jsonl
from .types import DecisionProvider, RunMode, RunResult, SpecialistDispatcher, SpecialistInvocation

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _new_id() -> str:
    return str(uuid4())


def run_scenario_case(
    *,
    mode: RunMode,
    case_id: str,
    trace_path: str,
    decision_provider: DecisionProvider | None = None,
    specialist_dispatcher: SpecialistDispatcher | None = None,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> RunResult:
    scenario = load_scenario()
    scenario_case = find_scenario_case(scenario, case_id)
    next_id = id_factory or _new_id
    run_id = next_id()
    sink = MemoryEventSink(run_id=run_id, source="python", clock=clock, id_factory=next_id)
    dispatcher = specialist_dispatcher or RecordingSpecialistDispatcher()

    sink.emit("run.created", {
        "scenario_id": scenario.scenario_id,
        "case_id": scenario_case.id,
        "mode": mode,
    })
    sink.emit("run.started", {"case_id": scenario_case.id, "mode": mode})
    sink.emit("step.started", {"step": "classify"})

    if mode == "deterministic":
        raw_decision: object = classify_deterministically(scenario_case.request)
        raw_decision = {"route": raw_decision.route, "confidence": raw_decision.confidence}
    else:
        provider = decision_provider or ScriptedDecisionProvider.from_file()
        sink.emit("model.requested", {"case_id": scenario_case.id})
        raw_decision = provider.classify(case_id=scenario_case.id, request=scenario_case.request)
        sink.emit("model.completed", {"case_id": scenario_case.id, "decision": deepcopy(raw_decision)})

    routed = route_decision(raw_decision)
    if isinstance(routed, RejectedRoute):
        sink.emit("route.rejected", {
            "route": routed.rejected_route,
            "failure_code": routed.failure_code,
        })
        sink.emit("step.failed", {"step": "classify", "failure_code": routed.failure_code})
        sink.emit("run.failed", {"status": "FAILED", "failure_code": routed.failure_code})
        result = RunResult(
            "1.0",
            run_id,
            "support-triage",
            scenario_case.id,
            mode,
            "FAILED",
            None,
            False,
            routed.failure_code,
            trace_path,
        )
        validation = validate_run_result(result.to_dict())
        if not validation.ok:
            raise ValueError(f"Invalid run result: {'; '.join(validation.errors)}")
        write_jsonl(trace_path, sink.events)
        return result

    decision = routed
    sink.emit("route.selected", {"route": decision.route, "confidence": decision.confidence})
    sink.emit("step.completed", {"step": "classify", "route": decision.route})
    specialist_step = f"specialist.{decision.route}"
    sink.emit("step.started", {"step": specialist_step, "route": decision.route})
    dispatcher.dispatch(SpecialistInvocation(decision.route, scenario_case.request))
    sink.emit("step.completed", {"step": specialist_step, "route": decision.route})
    sink.emit("run.completed", {"status": "SUCCEEDED", "route": decision.route})
    result = RunResult(
        "1.0",
        run_id,
        "support-triage",
        scenario_case.id,
        mode,
        "SUCCEEDED",
        decision.route,
        True,
        None,
        trace_path,
    )
    validation = validate_run_result(result.to_dict())
    if not validation.ok:
        raise ValueError(f"Invalid run result: {'; '.join(validation.errors)}")
    write_jsonl(trace_path, sink.events)
    return result
