from dataclasses import dataclass
from typing import Callable, Awaitable, Literal, Protocol

WORKER_IDS=('order-details','payment-status','delivery-status')
WorkerId=Literal['order-details','payment-status','delivery-status']
ExecutionMode=Literal['sequential','parallel']
StepStatus=Literal['PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED']
RunStateStatus=Literal['RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED','UNKNOWN']
StateLoadReason=Literal['UNKNOWN_VERSION','SCHEMA_INVALID','DIGEST_MISMATCH','BINDING_MISMATCH','TRUNCATED','MISSING_SNAPSHOT']
WorkerOutput=dict[str,object]
WorkerOutcome=dict[str,object]
StepRecord=dict[str,object]
RunStateDocument=dict[str,object]
CanonicalOutcomes=tuple[WorkerOutcome,WorkerOutcome,WorkerOutcome]
Brief=dict[str,object]
RunResult=dict[str,object]
EffectPayload=dict[str,object]
RefundOutcome=dict[str,object]
EffectOutcome=dict[str,object]
LedgerRecord=dict[str,object]
SubmitResult=dict[str,object]
LookupResult=dict[str,object]
ApprovalMetadata=dict[str,object]
ApprovalRecord=dict[str,object]
AuditRecord=dict[str,object]
RecoveryControls=dict[str,bool]

@dataclass(frozen=True)
class WorkerInput:
    order_id:str

@dataclass(frozen=True)
class ValidationResult:
    valid:bool
    value:object=None

class WorkerExecutionError(Exception):
    pass

@dataclass(frozen=True)
class StateBinding:
    case_id:str
    execution_mode:ExecutionMode
    requested_order_id:str
    concurrency_limit:int

class StateLoadError(Exception):
    def __init__(self,reason:StateLoadReason,detail:str):
        self.reason=reason
        super().__init__(f'Run state load failed: {reason} ({detail})')

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
    store:object=None
    controls:RecoveryControls|None=None
    completion_order:tuple[WorkerId,...]|None=None
    on_crash:Callable[[],object]|None=None
    queue:tuple[WorkerId,...]|None=None

@dataclass(frozen=True)
class ExecutionSummary:
    outcomes:list[WorkerOutcome]
    peak_concurrency:int
    cancelled_before:WorkerId|None=None

@dataclass(frozen=True)
class CaseSpec:
    case_id:str
    execution_mode:ExecutionMode
    worker_fixture:str
    completion_order:tuple[WorkerId,...]
    approval:ApprovalMetadata
    controls:RecoveryControls|None=None
    duplicate_key:bool=False

@dataclass(frozen=True)
class Scenario:
    schema_version:str
    scenario_id:str
    order_id:str
    cases:tuple[CaseSpec,...]
