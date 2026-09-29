from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from .executor import ToolExecutionError, ToolTimeoutError, invoke_tool
from .scenario import find_scenario_case, load_scenario
from .schemas import validate_model_turn, validate_run_result
from .scripted_model import ScriptedModelProvider
from .tool_registry import create_fake_tool_registry
from .trace import MemoryEventSink, write_jsonl
from .types import (
    FailureCode,
    ModelProvider,
    RunMode,
    RunResult,
    ScenarioSuccessCase,
    ToolObservation,
    ToolRegistry,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _new_id() -> str:
    return str(uuid4())


async def run_scenario_case(
    *,
    mode: RunMode,
    case_id: str,
    trace_path: str,
    model_provider: ModelProvider | None = None,
    tool_registry: ToolRegistry | None = None,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> RunResult:
    scenario = load_scenario()
    scenario_case = find_scenario_case(scenario, case_id)
    if scenario_case.mode != mode:
        raise ValueError(f"Requested mode {mode} does not match canonical case mode {scenario_case.mode}.")

    next_id = id_factory or _new_id
    run_id = next_id()
    sink = MemoryEventSink(run_id=run_id, source="python", clock=clock, id_factory=next_id)
    registry = tool_registry or create_fake_tool_registry()
    model_steps = 0
    tokens_used = 0
    tool_invocations = 0

    sink.emit("run.created", {"scenario_id": scenario.scenario_id, "case_id": scenario_case.id, "mode": mode})
    sink.emit("run.started", {"case_id": scenario_case.id, "mode": mode})

    async def finish_failure(failure_code: FailureCode) -> RunResult:
        sink.emit("run.failed", {
            "status": "FAILED",
            "failure_code": failure_code,
            "model_steps": model_steps,
            "tokens_used": tokens_used,
            "tool_invocations": tool_invocations,
        })
        result = RunResult(
            "1.0", run_id, "order-investigation", scenario_case.id, mode,
            "FAILED", None, failure_code, model_steps, tokens_used,
            tool_invocations, trace_path,
        )
        validation = validate_run_result(result.to_dict())
        if not validation.ok:
            raise ValueError(f"Invalid run result: {'; '.join(validation.errors)}")
        write_jsonl(trace_path, list(sink.events))
        return result

    async def finish_success(answer: str) -> RunResult:
        sink.emit("run.completed", {
            "status": "SUCCEEDED",
            "answer": answer,
            "model_steps": model_steps,
            "tokens_used": tokens_used,
            "tool_invocations": tool_invocations,
        })
        result = RunResult(
            "1.0", run_id, "order-investigation", scenario_case.id, mode,
            "SUCCEEDED", answer, None, model_steps, tokens_used,
            tool_invocations, trace_path,
        )
        validation = validate_run_result(result.to_dict())
        if not validation.ok:
            raise ValueError(f"Invalid run result: {'; '.join(validation.errors)}")
        write_jsonl(trace_path, list(sink.events))
        return result

    if mode == "direct":
        if not isinstance(scenario_case, ScenarioSuccessCase) or scenario_case.direct_call is None:
            raise ValueError(f"Direct case {scenario_case.id} must define a direct call.")
        call = scenario_case.direct_call
        definition = registry.resolve(call.tool)
        if definition is None:
            return await finish_failure("UNKNOWN_TOOL")
        arguments_validation = definition.validate_arguments(call.arguments)
        if not arguments_validation.ok:
            return await finish_failure("INVALID_TOOL_ARGUMENTS")
        sink.emit("tool.requested", {"call_id": call.call_id, "tool": call.tool, "arguments": arguments_validation.value})
        tool_invocations += 1
        try:
            output = await invoke_tool(definition, arguments_validation.value)
            observation = ToolObservation(call.call_id, definition.name, output)
            sink.emit("tool.completed", {
                "call_id": call.call_id,
                "tool": definition.name,
                "observation": {"call_id": observation.call_id, "tool": observation.tool, "output": observation.output},
            })
            order_id = output.get("order_id")
            status = output.get("status")
            if not isinstance(order_id, str) or not isinstance(status, str):
                raise ToolExecutionError(definition.name, "lookup_order returned an invalid observation.")
            return await finish_success(f"Order {order_id} status is {status}.")
        except Exception as error:
            failure_code: FailureCode = "TOOL_TIMEOUT" if isinstance(error, ToolTimeoutError) else "TOOL_EXECUTION_FAILED"
            sink.emit("tool.failed", {"call_id": call.call_id, "tool": definition.name, "failure_code": failure_code})
            return await finish_failure(failure_code)

    provider = model_provider or ScriptedModelProvider.from_file()
    observations: list[ToolObservation] = []

    while True:
        if model_steps >= scenario_case.max_steps:
            sink.emit("budget.exceeded", {"budget": "step", "consumed": model_steps, "limit": scenario_case.max_steps, "failure_code": "STEP_BUDGET_EXCEEDED"})
            return await finish_failure("STEP_BUDGET_EXCEEDED")

        model_step = model_steps + 1
        sink.emit("model.requested", {"case_id": scenario_case.id, "model_step": model_step})
        model_steps = model_step

        try:
            raw_turn = await provider.next_turn(
                case_id=scenario_case.id,
                request=scenario_case.request,
                model_step=model_step,
                observations=tuple(deepcopy(observations)),
            )
        except Exception:
            sink.emit("model.failed", {"case_id": scenario_case.id, "model_step": model_step, "failure_code": "INVALID_MODEL_DECISION"})
            return await finish_failure("INVALID_MODEL_DECISION")

        sink.emit("model.completed", {"case_id": scenario_case.id, "model_step": model_step, "turn": raw_turn})
        turn_validation = validate_model_turn(raw_turn)
        if not turn_validation.ok:
            return await finish_failure("INVALID_MODEL_DECISION")
        turn = turn_validation.value
        usage = turn["usage"]
        assert isinstance(usage, dict)
        tokens_used += int(usage["input_tokens"]) + int(usage["output_tokens"])
        sink.emit("budget.consumed", {
            "model_steps": model_steps,
            "max_steps": scenario_case.max_steps,
            "tokens_used": tokens_used,
            "max_tokens": scenario_case.max_tokens,
        })

        if tokens_used > scenario_case.max_tokens:
            sink.emit("budget.exceeded", {"budget": "token", "consumed": tokens_used, "limit": scenario_case.max_tokens, "failure_code": "TOKEN_BUDGET_EXCEEDED"})
            return await finish_failure("TOKEN_BUDGET_EXCEEDED")

        decision = turn["decision"]
        assert isinstance(decision, dict)
        if decision["kind"] == "final":
            return await finish_success(str(decision["answer"]))

        tool_name = str(decision["tool"])
        definition = registry.resolve(tool_name)
        if definition is None:
            return await finish_failure("UNKNOWN_TOOL")
        arguments = decision["arguments"]
        arguments_validation = definition.validate_arguments(arguments)
        if not arguments_validation.ok:
            return await finish_failure("INVALID_TOOL_ARGUMENTS")

        if model_steps >= scenario_case.max_steps:
            sink.emit("budget.exceeded", {"budget": "step", "consumed": model_steps, "limit": scenario_case.max_steps, "failure_code": "STEP_BUDGET_EXCEEDED"})
            return await finish_failure("STEP_BUDGET_EXCEEDED")

        call_id = str(decision["call_id"])
        sink.emit("tool.requested", {"call_id": call_id, "tool": definition.name, "arguments": arguments_validation.value})
        tool_invocations += 1
        try:
            output = await invoke_tool(definition, arguments_validation.value)
            observation = ToolObservation(call_id, definition.name, output)
            sink.emit("tool.completed", {
                "call_id": call_id,
                "tool": definition.name,
                "observation": {"call_id": observation.call_id, "tool": observation.tool, "output": observation.output},
            })
            observations.append(observation)
        except Exception as error:
            failure_code = "TOOL_TIMEOUT" if isinstance(error, ToolTimeoutError) else "TOOL_EXECUTION_FAILED"
            sink.emit("tool.failed", {"call_id": call_id, "tool": definition.name, "failure_code": failure_code})
            return await finish_failure(failure_code)
