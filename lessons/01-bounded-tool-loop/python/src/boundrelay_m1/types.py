from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Generic, Literal, Protocol, TypeAlias, TypeVar

ToolName: TypeAlias = Literal["lookup_order", "lookup_shipment"]
ToolSideEffect: TypeAlias = Literal["READ_ONLY"]
RunMode: TypeAlias = Literal["direct", "agent"]
RunStatus: TypeAlias = Literal["SUCCEEDED", "FAILED"]
FailureCode: TypeAlias = Literal[
    "UNKNOWN_TOOL",
    "INVALID_TOOL_ARGUMENTS",
    "TOOL_TIMEOUT",
    "TOOL_EXECUTION_FAILED",
    "STEP_BUDGET_EXCEEDED",
    "TOKEN_BUDGET_EXCEEDED",
    "INVALID_MODEL_DECISION",
]
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
]

TOOL_NAMES: tuple[ToolName, ...] = ("lookup_order", "lookup_shipment")
FAILURE_CODES: tuple[FailureCode, ...] = (
    "UNKNOWN_TOOL",
    "INVALID_TOOL_ARGUMENTS",
    "TOOL_TIMEOUT",
    "TOOL_EXECUTION_FAILED",
    "STEP_BUDGET_EXCEEDED",
    "TOKEN_BUDGET_EXCEEDED",
    "INVALID_MODEL_DECISION",
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
class ToolObservation:
    call_id: str
    tool: ToolName
    output: dict[str, object]


@dataclass(frozen=True)
class RunResult:
    schema_version: Literal["1.0"]
    run_id: str
    scenario_id: Literal["order-investigation"]
    case_id: str
    mode: RunMode
    status: RunStatus
    answer: str | None
    failure_code: FailureCode | None
    model_steps: int
    tokens_used: int
    tool_invocations: int
    trace_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DirectCall:
    call_id: str
    tool: ToolName
    arguments: dict[str, object]


@dataclass(frozen=True)
class ScenarioCaseBase:
    id: str
    mode: RunMode
    request: str
    max_steps: int
    max_tokens: int
    expected_model_steps: int
    expected_tokens_used: int
    expected_tool_invocations: int


@dataclass(frozen=True)
class ScenarioSuccessCase(ScenarioCaseBase):
    expected_status: Literal["SUCCEEDED"]
    expected_answer: str
    direct_call: DirectCall | None


@dataclass(frozen=True)
class ScenarioFailureCase(ScenarioCaseBase):
    mode: Literal["agent"]
    expected_status: Literal["FAILED"]
    expected_failure_code: FailureCode


ScenarioCase: TypeAlias = ScenarioSuccessCase | ScenarioFailureCase


@dataclass(frozen=True)
class ScenarioDefinition:
    schema_version: Literal["1.0"]
    scenario_id: Literal["order-investigation"]
    cases: tuple[ScenarioCase, ...]


class ModelProvider(Protocol):
    async def next_turn(
        self,
        *,
        case_id: str,
        request: str,
        model_step: int,
        observations: tuple[ToolObservation, ...],
    ) -> object: ...


@dataclass(frozen=True)
class ToolDefinition:
    name: ToolName
    side_effect: Literal["READ_ONLY"]
    timeout_ms: int
    validate_arguments: Callable[[object], ValidationResult[dict[str, object]]]
    invoke: Callable[[dict[str, object]], Awaitable[dict[str, object]]]


class ToolRegistry(Protocol):
    def resolve(self, name: str) -> ToolDefinition | None: ...
