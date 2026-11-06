"""The Google ADK wiring for the M2 router->handoff flow.

The flow runs fully offline on ADK's own machinery: a deterministic
ScriptedRouterModel (a custom ``BaseLlm``) replays the M2 fake-model
route decision as a function call; the M2 runner tail (closed decision
validation, the 0.80 confidence policy, handoff-envelope validation,
receiver-directory resolution, dispatch) is re-established inside the
handoff tool boundary. Receivers are deterministic tool functions (not
ADK sub-agents): ADK's transfer machinery forwards session history and
cannot express the M2 receiver_input envelope or a zero-dispatch
failure, so the directory lives inside the boundary where both checks
run before any dispatch. Code mode has no model turn, so the router is
a custom BaseAgent (ADK's workflow-agent shape) that classifies in
process and calls the same boundary.
"""
import asyncio
import contextlib
import json
import logging
from pathlib import Path
from uuid import uuid4

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from jsonschema import Draft202012Validator

from . import fixtures, results
from .attribution import build_attribution
from .fixtures import load_case

ROUTER_AGENT_NAME = "support_router"
CODE_ROUTER_AGENT_NAME = "code_router"
ROUTER_INSTRUCTION = (
    "You route support tickets: classify the request and call the "
    "handoff tool with the route and your confidence.")
HANDOFF_TOOL_NAME = "handoff_to_specialist"
APP_NAME = "boundrelay-m2-adk"

ROUTE_VALIDATOR = Draft202012Validator(fixtures.load_route_decision_schema())
HANDOFF_VALIDATOR = Draft202012Validator(fixtures.load_handoff_schema())

BILLING_KEYWORDS = ("charged", "charge", "invoice", "payment", "refund",
                    "billed")
TECHNICAL_KEYWORDS = ("error", "crash", "cannot log in", "can't log in",
                      "bug", "broken")


class MappingError(Exception):
    """Tooling-level mapping failure (never a domain result)."""


class MappedFailure(Exception):
    """A domain failure carried through the framework's error channel."""

    failure_code = None


class InvalidRouteDecisionFailure(MappedFailure):
    failure_code = "INVALID_ROUTE_DECISION"


class HandoffContextInvalidFailure(MappedFailure):
    failure_code = "HANDOFF_CONTEXT_INVALID"


class HandoffReceiverUnavailableFailure(MappedFailure):
    failure_code = "HANDOFF_RECEIVER_UNAVAILABLE"


def classify_with_code(request):
    """The M2 deterministic code-mode classifier (route, confidence 1.0)."""
    value = request.lower()
    if any(keyword in value for keyword in BILLING_KEYWORDS):
        route = "billing"
    elif any(keyword in value for keyword in TECHNICAL_KEYWORDS):
        route = "technical"
    else:
        route = "general"
    return {"route": route, "confidence": 1.0}


def apply_confidence_policy(decision):
    """The M2 0.80 confidence policy: below the threshold, fall back to
    general. The framework has no such policy - re-established here."""
    confidence = decision["confidence"]
    fallback_applied = confidence < fixtures.CONFIDENCE_THRESHOLD
    selected_route = "general" if fallback_applied else decision["route"]
    return {
        "proposed_route": decision["route"],
        "selected_route": selected_route,
        "confidence": confidence,
        "policy_outcome": "fallback" if fallback_applied else "selected",
        "fallback_applied": fallback_applied,
        "receiver": fixtures.RECEIVER_BY_ROUTE[selected_route],
    }


class RunLedger:
    """Shared run state: the classify step, the selection, the dispatch."""

    def __init__(self):
        self.classify_counted = False
        self.selection = None
        self.receivers_dispatched = []

    def count_classify(self):
        if self.classify_counted:
            raise MappingError("The classify step was counted twice")
        self.classify_counted = True

    def record_selection(self, selection):
        self.selection = dict(selection)

    def record_receiver(self, name):
        self.receivers_dispatched.append(name)

    def step_records(self, mode):
        del mode
        records = [("classify", 1)]
        records.extend((f"receiver.{name}", 1)
                       for name in self.receivers_dispatched)
        return records


def _closed_errors(validator, value):
    return sorted(validator.iter_errors(value),
                  key=lambda error: list(error.absolute_path))


def _first_error_message(errors):
    return errors[0].message


def validate_route_decision(decision):
    """Closed validation of the router decision (route-decision contract)."""
    errors = _closed_errors(ROUTE_VALIDATOR, decision)
    if errors:
        raise InvalidRouteDecisionFailure(
            f"The route decision violates the closed schema: "
            f"{_first_error_message(errors)}")


def execute_handoff(decision, case, ledger, directory):
    """The M2 runner tail, re-established as one closed boundary.

    Decision validation -> confidence policy -> handoff envelope
    validation -> receiver-directory resolution -> dispatch. Every
    failure raises before the receiver is invoked (zero dispatch).
    """
    validate_route_decision(decision)
    selection = apply_confidence_policy(decision)
    ledger.record_selection(selection)
    receiver_input = {"ticket_id": case.ticket_id,
                      "request_text": case.request}
    failure = case.failure or {}
    for field in failure.get("omit_receiver_input_fields", ()):
        receiver_input.pop(field)
    envelope = {
        "schema_version": "1.0",
        "handoff_id": str(uuid4()),
        "sender": "support-router",
        "receiver": selection["receiver"],
        "sender_intent": {
            "route": selection["proposed_route"],
            "confidence": selection["confidence"],
            "policy_outcome": selection["policy_outcome"],
        },
        "receiver_input": receiver_input,
    }
    errors = _closed_errors(HANDOFF_VALIDATOR, envelope)
    if errors:
        raise HandoffContextInvalidFailure(
            f"The handoff envelope violates the closed schema: "
            f"{_first_error_message(errors)}")
    unavailable = failure.get("unavailable_receivers", ())
    handle = (directory.get(selection["receiver"])
              if selection["receiver"] not in unavailable else None)
    if handle is None:
        raise HandoffReceiverUnavailableFailure(
            f"Receiver unavailable: {selection['receiver']}")
    handle(dict(receiver_input))
    ledger.record_receiver(selection["receiver"])
    return {"dispatched": True, "receiver": selection["receiver"],
            "fallback_applied": selection["fallback_applied"]}


def create_receiver_directory(unavailable=()):
    """The M2 static receiver directory: name -> deterministic handle."""
    handles = {}
    for name in fixtures.RECEIVER_NAMES:
        if name in unavailable:
            continue
        def handle(receiver_input, _name=name):
            del receiver_input
            return None
        handles[name] = handle
    return handles


class ScriptedRouterModel(BaseLlm):
    """Deterministic BaseLlm replaying the M2 fake-model decision.

    Turn 1 validates the decision against the closed route-decision
    contract (the M2 validate-before-policy checkpoint) and emits it as
    the handoff function call; turn 2 is the wrap-up text the ADK auto
    flow requires after every tool response (the framework re-invokes
    the model even when the tool ends the work - the turn is
    framework-owned and unpriced by the M2 attribution).
    """

    model: str = "boundrelay-scripted-router"
    decision: object = None
    ledger: object = None
    turns_consumed: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        if stream:
            raise MappingError("Streaming is deliberately unused")
        if self.turns_consumed == 0:
            self.turns_consumed = 1
            self.ledger.count_classify()
            validate_route_decision(self.decision)
            part = types.Part(function_call=types.FunctionCall(
                name=HANDOFF_TOOL_NAME, args=dict(self.decision)))
        elif self.turns_consumed == 1:
            self.turns_consumed = 2
            part = types.Part(text="Handoff dispatch acknowledged.")
        else:
            raise MappingError(
                "Scripted router model turns exhausted before the run ended")
        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=12, candidates_token_count=9,
                total_token_count=21),
        )


def build_scripted_model(case, ledger, decision=None):
    """The scripted router model from the fixture decision (test seam:
    ``decision`` replaces the fixture decision for taxonomy proofs)."""
    return ScriptedRouterModel(
        decision=case.decision if decision is None else dict(decision),
        ledger=ledger)


def build_handoff_tool(case, ledger, directory):
    """The handoff boundary as an ADK function tool.

    The tool body is the M2 runner tail: closed validation, policy,
    envelope, directory, dispatch. Exceptions propagate (no on-tool
    error callbacks are installed), so the framework's error channel
    carries the mapped failure out of the run.
    """

    def handoff_to_specialist(route, confidence, tool_context=None):
        del tool_context
        return execute_handoff({"route": route, "confidence": confidence},
                               case, ledger, directory)

    return FunctionTool(handoff_to_specialist)


class CodeRouterAgent(BaseAgent):
    """The code-mode router: no model turn, so a custom BaseAgent.

    ADK's LlmAgent would fake a model behind the deterministic keyword
    classifier; the workflow-agent shape keeps the M2 attribution
    honest (classify priced as route, not model_decision) while the
    Runner still drives the run and the native event stream.
    """

    bound_case: object = None
    ledger: object = None
    directory: object = None

    async def _run_async_impl(self, ctx: InvocationContext):
        del ctx
        decision = classify_with_code(self.bound_case.request)
        self.ledger.count_classify()
        yield Event(author=self.name, content=types.Content(
            role="model", parts=[types.Part(text=(
                f"code classify: route={decision['route']} "
                f"confidence={decision['confidence']}"))]))
        ack = execute_handoff(decision, self.bound_case, self.ledger,
                              self.directory)
        yield Event(author=self.name, content=types.Content(
            role="model", parts=[types.Part(text=(
                f"handoff accepted: {ack['receiver']}"))]))


def classify_run_exception(error):
    """Map a run exception onto the M2 failure taxonomy via cause chain."""
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, MappedFailure):
            return current.failure_code
        current = current.__cause__
    return None


def write_native_trace(trace_path, records):
    """Write ADK's native event stream, one JSON event per line."""
    lines = [json.dumps(record, ensure_ascii=True, allow_nan=False)
             for record in records]
    path = Path(trace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _dump_event(event):
    return event.model_dump(mode="json", exclude_none=True)


@contextlib.contextmanager
def _quiet_framework_logs():
    """Silence ADK's duplicate error logging during the run.

    The node runner logs every mapped failure with a full traceback
    before emitting its error event; the mapping already classifies the
    exception and publishes the terminal record, so the log line is
    noise (stderr must stay clean for the CLI contract). ADK 2.13 names
    its loggers 'google_adk.*' (and genai uses 'google.*').
    """
    saved = []
    for name in ("google_adk", "google"):
        logger = logging.getLogger(name)
        saved.append((logger, logger.level))
        logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        for logger, level in saved:
            logger.setLevel(level)


async def _execute(case, ledger, decision):
    """Drive one case through the Runner; return (events, error|None)."""
    directory = create_receiver_directory()
    if case.router_mode == "code":
        agent = CodeRouterAgent(name=CODE_ROUTER_AGENT_NAME,
                                description="M2 code-mode router",
                                bound_case=case, ledger=ledger,
                                directory=directory)
    else:
        model = build_scripted_model(case, ledger, decision)
        agent = LlmAgent(name=ROUTER_AGENT_NAME,
                         instruction=ROUTER_INSTRUCTION, model=model,
                         tools=[build_handoff_tool(case, ledger, directory)])
    runner = Runner(app_name=APP_NAME, agent=agent,
                    session_service=InMemorySessionService())
    events = []
    try:
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id="boundrelay")
        message = types.Content(role="user",
                                parts=[types.Part(text=case.request)])
        async for event in runner.run_async(
                user_id="boundrelay", session_id=session.id,
                new_message=message):
            events.append(_dump_event(event))
    except Exception as error:  # noqa: BLE001 - taxonomy boundary
        return events, error
    return events, None


def _finish(run_id, trace_path, case, ledger, *, status, failure_code=None):
    selection = ledger.selection
    attribution = build_attribution(
        ledger.step_records(case.router_mode),
        {"latency_ms": case.latency_ms, "price_table": case.price_table},
        case.router_mode)
    return results.assemble_result(
        run_id=run_id, trace_path=trace_path, case_id=case.case_id,
        router_mode=case.router_mode, status=status,
        proposed_route=selection["proposed_route"] if selection else None,
        selected_route=selection["selected_route"] if selection else None,
        receiver=selection["receiver"] if selection else None,
        fallback_applied=(selection["fallback_applied"] if selection
                          else False),
        specialist_invoked=status == "SUCCEEDED",
        failure_code=failure_code, attribution=attribution)


def run_case(case_id, trace_path, *, decision=None):
    """Run one parity case through the ADK machinery (offline, scripted).

    ``decision`` optionally replaces the scripted model decision (test
    seam for taxonomy proofs). Returns the M2-schema result dict.
    Domain failures come back as FAILED results; unknown cases and
    non-taxonomy errors raise (tooling failure).
    """
    case = load_case(case_id)
    run_id = str(uuid4())
    ledger = RunLedger()
    with _quiet_framework_logs():
        events, error = asyncio.run(_execute(case, ledger, decision))
    write_native_trace(trace_path, events)
    if error is not None:
        failure_code = classify_run_exception(error)
        if failure_code is None:
            raise error
        return _finish(run_id, trace_path, case, ledger, status="FAILED",
                       failure_code=failure_code)
    if ledger.selection is None or len(ledger.receivers_dispatched) != 1:
        raise MappingError("The run completed without a dispatched receiver")
    return _finish(run_id, trace_path, case, ledger, status="SUCCEEDED",
                   failure_code=None)
