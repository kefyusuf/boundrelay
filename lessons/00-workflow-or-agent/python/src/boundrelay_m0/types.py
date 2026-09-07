from dataclasses import asdict, dataclass
from typing import Literal, Protocol, TypeAlias

Route: TypeAlias = Literal["billing", "technical", "general"]
RunMode: TypeAlias = Literal["deterministic", "model"]
RunStatus: TypeAlias = Literal["SUCCEEDED", "FAILED"]
FailureCode: TypeAlias = Literal["INVALID_ROUTE_DECISION"]
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
]

ROUTES: tuple[Route, ...] = ("billing", "technical", "general")
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"run.completed", "run.failed"})


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    confidence: float


@dataclass(frozen=True)
class RunResult:
    schema_version: Literal["1.0"]
    run_id: str
    scenario_id: Literal["support-triage"]
    case_id: str
    mode: RunMode
    status: RunStatus
    selected_route: Route | None
    specialist_invoked: bool
    failure_code: FailureCode | None
    trace_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioSuccessCase:
    id: str
    request: str
    expected_route: Route


@dataclass(frozen=True)
class ScenarioFailureCase:
    id: str
    request: str
    expected_failure_code: FailureCode


ScenarioCase: TypeAlias = ScenarioSuccessCase | ScenarioFailureCase


@dataclass(frozen=True)
class ScenarioDefinition:
    schema_version: Literal["1.0"]
    scenario_id: Literal["support-triage"]
    routes: tuple[Route, ...]
    cases: tuple[ScenarioCase, ...]


@dataclass(frozen=True)
class SpecialistInvocation:
    route: Route
    request: str


class DecisionProvider(Protocol):
    def classify(self, *, case_id: str, request: str) -> object: ...


class SpecialistDispatcher(Protocol):
    def dispatch(self, invocation: SpecialistInvocation) -> None: ...
