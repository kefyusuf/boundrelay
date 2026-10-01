from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Generic, Literal, Protocol, TypeAlias, TypeVar

Route: TypeAlias = Literal["billing", "technical", "general"]
RouterMode: TypeAlias = Literal["code", "model"]
ReceiverName: TypeAlias = Literal[
    "billing-specialist",
    "technical-specialist",
    "general-specialist",
]
PolicyOutcome: TypeAlias = Literal["selected", "fallback"]
FailureCode: TypeAlias = Literal[
    "INVALID_ROUTE_DECISION",
    "HANDOFF_CONTEXT_INVALID",
    "HANDOFF_RECEIVER_UNAVAILABLE",
]
RunStatus: TypeAlias = Literal["SUCCEEDED", "FAILED"]
EventSource: TypeAlias = Literal["typescript", "python"]
EventType: TypeAlias = Literal[
    "run.created",
    "run.started",
    "run.completed",
    "run.failed",
    "step.started",
    "step.completed",
    "step.failed",
    "model.requested",
    "model.completed",
    "model.failed",
    "route.selected",
    "route.rejected",
    "tool.requested",
    "tool.completed",
    "tool.failed",
    "budget.consumed",
    "budget.exceeded",
    "handoff.requested",
    "handoff.accepted",
    "handoff.rejected",
]
ReceiverInputField: TypeAlias = Literal["ticket_id", "request_text"]

ROUTES: tuple[Route, ...] = ("billing", "technical", "general")
RECEIVER_NAMES: tuple[ReceiverName, ...] = (
    "billing-specialist",
    "technical-specialist",
    "general-specialist",
)
FAILURE_CODES: tuple[FailureCode, ...] = (
    "INVALID_ROUTE_DECISION",
    "HANDOFF_CONTEXT_INVALID",
    "HANDOFF_RECEIVER_UNAVAILABLE",
)

T = TypeVar("T")


@dataclass(frozen=True)
class ValidationSuccess(Generic[T]):
    value: T

    @property
    def ok(self) -> Literal[True]:
        return True


@dataclass(frozen=True)
class ValidationFailure:
    errors: tuple[str, ...]

    @property
    def ok(self) -> Literal[False]:
        return False


ValidationResult: TypeAlias = ValidationSuccess[T] | ValidationFailure


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
    schema_version: Literal["1.0"]
    handoff_id: str
    sender: Literal["support-router"]
    receiver: ReceiverName
    sender_intent: SenderIntent
    receiver_input: ReceiverInput


@dataclass(frozen=True)
class HandoffResult:
    schema_version: Literal["1.0"]
    run_id: str
    scenario_id: Literal["support-handoff"]
    case_id: str
    router_mode: RouterMode
    status: RunStatus
    proposed_route: Route | None
    selected_route: Route | None
    receiver: ReceiverName | None
    fallback_applied: bool
    specialist_invoked: bool
    failure_code: FailureCode | None
    trace_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RunEvent:
    schema_version: Literal["1.0"]
    event_id: str
    run_id: str
    sequence: int
    type: EventType
    timestamp: str
    source: EventSource
    data: dict[str, object]


@dataclass(frozen=True)
class ScenarioCase:
    id: str
    ticket_id: str
    request: str
    router_mode: RouterMode
    expected_status: RunStatus
    expected_proposed_route: Route
    expected_confidence: float
    expected_selected_route: Route
    expected_receiver: ReceiverName
    expected_policy_outcome: PolicyOutcome
    expected_fallback_applied: bool
    expected_specialist_invoked: bool
    expected_failure_code: FailureCode | None = None
    failure_ref: str | None = None


@dataclass(frozen=True)
class ScenarioDefinition:
    schema_version: Literal["1.0"]
    scenario_id: Literal["support-handoff"]
    confidence_threshold: float
    route_receivers: dict[Route, ReceiverName]
    cases: tuple[ScenarioCase, ...]


@dataclass(frozen=True)
class OmitReceiverInputFailure:
    omit_receiver_input_fields: tuple[ReceiverInputField, ...]


@dataclass(frozen=True)
class UnavailableReceiversFailure:
    unavailable_receivers: tuple[ReceiverName, ...]


FailureFixture: TypeAlias = OmitReceiverInputFailure | UnavailableReceiversFailure
FailureFixtures: TypeAlias = dict[str, FailureFixture]


class RouteDecisionProvider(Protocol):
    async def next_decision(self, *, case_id: str, request: str) -> object: ...


@dataclass(frozen=True)
class ReceiverDefinition:
    name: ReceiverName
    handle: Callable[[ReceiverInput], Awaitable[None]]


class ReceiverDirectory(Protocol):
    def resolve(self, name: str) -> ReceiverDefinition | None: ...
