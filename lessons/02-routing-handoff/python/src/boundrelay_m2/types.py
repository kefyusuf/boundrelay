from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

Route = Literal['billing', 'technical', 'general']
RouterMode = Literal['code', 'model']
ReceiverName = Literal['billing-specialist', 'technical-specialist', 'general-specialist']
PolicyOutcome = Literal['selected', 'fallback']
FailureCode = Literal['INVALID_ROUTE_DECISION', 'HANDOFF_CONTEXT_INVALID', 'HANDOFF_RECEIVER_UNAVAILABLE']
EventSource = Literal['typescript', 'python']
EventType = Literal['run.created', 'run.started', 'run.completed', 'run.failed', 'model.requested', 'model.completed', 'route.selected', 'route.rejected', 'handoff.requested', 'handoff.accepted', 'handoff.rejected']


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    confidence: float


@dataclass(frozen=True)
class RouteSelection:
    proposed_route: Route
    selected_route: Route
    confidence: float
    policy_outcome: PolicyOutcome
    fallback_applied: bool
    receiver: ReceiverName


@dataclass(frozen=True)
class ReceiverInput:
    ticket_id: str
    request_text: str


@dataclass(frozen=True)
class SenderIntent:
    route: Route
    confidence: float
    policy_outcome: PolicyOutcome


@dataclass(frozen=True)
class HandoffEnvelope:
    schema_version: str
    handoff_id: str
    sender: str
    receiver: ReceiverName
    sender_intent: SenderIntent
    receiver_input: ReceiverInput


@dataclass(frozen=True)
class HandoffResult:
    schema_version: str
    run_id: str
    scenario_id: str
    case_id: str
    router_mode: RouterMode
    status: Literal['SUCCEEDED', 'FAILED']
    proposed_route: Route | None
    selected_route: Route | None
    receiver: ReceiverName | None
    fallback_applied: bool
    specialist_invoked: bool
    failure_code: FailureCode | None
    trace_path: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ScenarioCase:
    id: str
    ticket_id: str
    request: str
    router_mode: RouterMode
    expected_status: str
    expected_proposed_route: Route
    expected_confidence: float
    expected_selected_route: Route
    expected_receiver: ReceiverName
    expected_policy_outcome: PolicyOutcome
    expected_fallback_applied: bool
    expected_specialist_invoked: bool
    expected_failure_code: FailureCode | None
    failure_ref: str | None = None


@dataclass(frozen=True)
class ScenarioDefinition:
    schema_version: str
    scenario_id: str
    confidence_threshold: float
    route_receivers: dict[Route, ReceiverName]
    cases: tuple[ScenarioCase, ...]


@dataclass(frozen=True)
class ValidationResult[T]:
    ok: bool
    value: T | None = None
    errors: tuple[str, ...] = ()


class RouteDecisionProvider(Protocol):
    async def next_decision(self, *, case_id: str, request: str) -> object: ...


@dataclass(frozen=True)
class ReceiverDefinition:
    name: ReceiverName
    handle: Callable[[ReceiverInput], Awaitable[None]]


class ReceiverDirectory(Protocol):
    def resolve(self, name: str) -> ReceiverDefinition | None: ...
