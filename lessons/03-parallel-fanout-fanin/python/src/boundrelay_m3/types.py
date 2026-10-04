from dataclasses import dataclass
from typing import Callable, Awaitable, Literal, Protocol

WORKER_IDS=('order-details','payment-status','delivery-status')
WorkerId=Literal['order-details','payment-status','delivery-status']
ExecutionMode=Literal['sequential','parallel']
WorkerOutput=dict[str,object]
WorkerOutcome=dict[str,object]
CanonicalOutcomes=tuple[WorkerOutcome,WorkerOutcome,WorkerOutcome]
Brief=dict[str,object]
RunResult=dict[str,object]

@dataclass(frozen=True)
class WorkerInput:
    order_id:str

@dataclass(frozen=True)
class ValidationResult:
    valid:bool
    value:object=None

class WorkerExecutionError(Exception):
    pass

class WorkerControl(Protocol):
    def acknowledge_outcome(self,worker_id:WorkerId)->None: ...
    def begin_drain(self)->None: ...

class WorkerProvider(WorkerControl,Protocol):
    async def read(self,worker_id:WorkerId,input:WorkerInput)->object: ...

@dataclass(frozen=True)
class WorkerDefinition:
    id:WorkerId
    handle:Callable[[WorkerInput],Awaitable[object]]

class WorkerDirectory(Protocol):
    def resolve(self,worker_id:WorkerId)->WorkerDefinition|None: ...

WorkerLifecycle=dict[str,object]
WorkerObserver=Callable[[WorkerLifecycle],None]

@dataclass(frozen=True)
class ExecutorOptions:
    mode:ExecutionMode
    input:WorkerInput
    directory:WorkerDirectory
    control:WorkerControl
    observer:WorkerObserver

@dataclass(frozen=True)
class ExecutionSummary:
    outcomes:list[WorkerOutcome]
    peak_concurrency:int

@dataclass(frozen=True)
class CaseSpec:
    case_id:str
    execution_mode:ExecutionMode
    worker_fixture:str
    completion_order:tuple[WorkerId,...]

@dataclass(frozen=True)
class Scenario:
    schema_version:str
    scenario_id:str
    order_id:str
    cases:tuple[CaseSpec,...]
