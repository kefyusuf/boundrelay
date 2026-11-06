"""The OpenAI Agents SDK wiring for the M1 bounded tool loop.

The SDK's Agent/Runner machinery runs fully offline: a deterministic
ScriptedAgentModel (a custom ``Model`` implementation) replays the M1
fake-model turns, injected through RunConfig's model/model-provider
override. The M1 fake tools become SDK function tools whose closed
argument validation (contracts/tools schemas) raises before invocation;
the failure taxonomy is preserved inside the tools. SDK max_turns
carries the step budget and MaxTurnsExceeded maps to
STEP_BUDGET_EXCEEDED; token accounting comes from the scripted usage.
"""
import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from jsonschema import Draft202012Validator

from agents import Agent, MaxTurnsExceeded, ModelBehaviorError, ModelProvider, RunConfig, Runner
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tool import FunctionTool, set_function_tool_failure_error_function
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from . import fixtures, results
from .attribution import build_attribution
from .fixtures import load_case

AGENT_NAME = "boundrelay-m1-order-investigator"
AGENT_INSTRUCTIONS = (
    "You investigate order questions using only the registered read-only "
    "lookup tools, then answer from the observations."
)
TOOL_TIMEOUT_MS = 100
UNKNOWN_TOOL_MARKER = "not found in agent"


class MappingError(Exception):
    """Tooling-level mapping failure (never a domain result)."""


class MappedFailure(Exception):
    """A domain failure carried through the SDK exception channel."""

    failure_code = None

    def __init__(self, message):
        super().__init__(message)


class UnknownToolFailure(MappedFailure):
    failure_code = "UNKNOWN_TOOL"


class InvalidToolArgumentsFailure(MappedFailure):
    failure_code = "INVALID_TOOL_ARGUMENTS"


class ToolTimeoutFailure(MappedFailure):
    failure_code = "TOOL_TIMEOUT"


class ToolExecutionFailure(MappedFailure):
    failure_code = "TOOL_EXECUTION_FAILED"


class StepBudgetExceededFailure(MappedFailure):
    failure_code = "STEP_BUDGET_EXCEEDED"


class TokenBudgetExceededFailure(MappedFailure):
    failure_code = "TOKEN_BUDGET_EXCEEDED"


@dataclass
class RunLedger:
    """Shared budget/counter state for one run (model + tools cooperate)."""

    max_steps: int
    max_tokens: int
    model_steps: int = 0
    tokens_used: int = 0
    tool_invocations: int = 0
    tool_counts: dict = field(default_factory=dict)

    def record_model_turn(self, input_tokens, output_tokens):
        self.model_steps += 1
        self.tokens_used += int(input_tokens) + int(output_tokens)

    def token_budget_exceeded(self):
        return self.tokens_used > self.max_tokens

    def record_tool(self, name):
        self.tool_invocations += 1
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1

    def step_records(self, mode):
        model = [] if mode == "direct" else [("model", self.model_steps)]
        return model + [(f"tool.{name}", count)
                        for name, count in self.tool_counts.items()]


class ScriptedAgentModel(Model):
    """Deterministic Model replaying the M1 fake-model turns (no network).

    Each get_response call consumes one scripted turn: usage flows into
    the ledger (token budget checked at the M1 checkpoint, before the
    decision is dispatched), then the decision becomes a normalized SDK
    output item (function_call or assistant message).
    """

    def __init__(self, turns, ledger):
        self._turns = list(turns)
        self._ledger = ledger

    @property
    def remaining_turns(self):
        return len(self._turns)

    def _pop_turn(self):
        if not self._turns:
            raise MappingError("Scripted model turns exhausted before the run ended")
        return self._turns.pop(0)

    def _usage(self, turn):
        usage = turn["usage"]
        return Usage(
            requests=1,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["input_tokens"] + usage["output_tokens"],
        )

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id,
        conversation_id,
        prompt,
    ):
        turn = self._pop_turn()
        usage = turn["usage"]
        self._ledger.record_model_turn(usage["input_tokens"], usage["output_tokens"])
        if self._ledger.token_budget_exceeded():
            raise TokenBudgetExceededFailure(
                f"Token budget exceeded: {self._ledger.tokens_used} > {self._ledger.max_tokens}")
        decision = turn["decision"]
        if decision["kind"] == "final":
            output_item = ResponseOutputMessage(
                id=f"msg-{self._ledger.model_steps}",
                type="message",
                role="assistant",
                status="completed",
                content=[ResponseOutputText(
                    text=decision["answer"],
                    type="output_text",
                    annotations=[],
                    logprobs=[],
                )],
            )
        else:
            output_item = ResponseFunctionToolCall(
                id=decision["call_id"],
                call_id=decision["call_id"],
                type="function_call",
                name=decision["tool"],
                arguments=json.dumps(decision["arguments"], ensure_ascii=True),
            )
        return ModelResponse(
            output=[output_item],
            usage=self._usage(turn),
            response_id=f"resp-{self._ledger.model_steps}",
        )

    def stream_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id,
        conversation_id,
        prompt,
    ):
        raise NotImplementedError(
            "Streaming is deliberately unused: the mapping drives Runner.run "
            "(non-streaming) and the native trace is the SDK run items")


class ScriptedModelProvider(ModelProvider):
    """Model provider resolved entirely from the scripted turns."""

    def __init__(self, model):
        self._model = model

    def get_model(self, model_name):
        return self._model


def _fixture_invoke(entry, label):
    async def invoke():
        if entry.get("behavior") == "timeout":
            await asyncio.Future()
        if entry.get("behavior") == "failure":
            raise RuntimeError(f"{label} scripted failure.")
        return deepcopy(entry["output"])
    return invoke


def build_function_tools(case, ledger):
    """Wrap the M1 fake tools as SDK function tools (closed validation).

    The on-invoke body reproduces the M1 tool boundary: closed argument
    validation -> pre-invocation step-budget check -> counted invocation
    under a timeout. Exceptions propagate to the mapping because the
    failure_error_function is disabled (None).
    """
    tools = {}
    for tool_name in ("lookup_order", "lookup_shipment"):
        schema = _tool_schema(tool_name)
        validator = Draft202012Validator(schema)
        table = case.fake_tools["orders" if tool_name == "lookup_order"
                                else "shipments"]

        async def on_invoke(tool_context, arguments_json, _name=tool_name,
                            _validator=validator, _table=table):
            try:
                raw = json.loads(arguments_json)
            except (json.JSONDecodeError, TypeError) as error:
                raise InvalidToolArgumentsFailure(
                    f"{_name} arguments are not valid JSON") from error
            errors = sorted(_validator.iter_errors(raw),
                            key=lambda error: list(error.absolute_path))
            if errors:
                raise InvalidToolArgumentsFailure(
                    f"{_name} arguments violate the closed schema: "
                    f"{errors[0].message}")
            if ledger.model_steps >= case.max_steps:
                raise StepBudgetExceededFailure(
                    f"Step budget exceeded: {ledger.model_steps} >= {case.max_steps}")
            ledger.record_tool(_name)
            try:
                output = await asyncio.wait_for(
                    _fixture_invoke(_table[raw[_argument_key(_name)]],
                                    f"{_name} {raw[_argument_key(_name)]}")(),
                    timeout=TOOL_TIMEOUT_MS / 1000)
            except TimeoutError as error:
                raise ToolTimeoutFailure(f"{_name} timed out") from error
            except MappedFailure:
                raise
            except Exception as error:
                raise ToolExecutionFailure(f"{_name} failed: {error}") from error
            return json.dumps(output, ensure_ascii=True, allow_nan=False)

        tool = FunctionTool(
            name=tool_name,
            description=f"Read-only scripted M1 tool: {tool_name}.",
            params_json_schema=schema,
            on_invoke_tool=on_invoke,
            # The closed contract schema is already strict; validation
            # happens inside the tool, not via SDK strict-mode rewriting.
            strict_json_schema=False,
        )
        set_function_tool_failure_error_function(tool, None)
        tools[tool_name] = tool
    return tools


def _tool_schema(tool_name):
    return fixtures.load_argument_schema(tool_name)


def _argument_key(tool_name):
    return "order_id" if tool_name == "lookup_order" else "shipment_id"


def classify_run_exception(error):
    """Map an SDK run exception onto the M1 failure taxonomy.

    The SDK wraps tool exceptions (UserError) and reports unknown tools
    (ModelBehaviorError "...not found in agent..."); the cause chain is
    walked so mapping exceptions raised inside tools resolve cleanly.
    """
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, MappedFailure):
            return current.failure_code
        if isinstance(current, MaxTurnsExceeded):
            return "STEP_BUDGET_EXCEEDED"
        if (isinstance(current, ModelBehaviorError)
                and UNKNOWN_TOOL_MARKER in str(current)):
            return "UNKNOWN_TOOL"
        current = current.__cause__
    return None


def _dump_raw(raw):
    dump = getattr(raw, "model_dump", None)
    if dump is not None:
        return dump(mode="json", exclude_none=True)
    return raw


def write_native_trace(trace_path, records):
    """Write the SDK's native telemetry, one JSON object per line."""
    lines = [json.dumps(record, ensure_ascii=True, allow_nan=False)
             for record in records]
    with open(trace_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _run_item_records(new_items):
    return [{"item_type": type(item).__name__, "raw_item": _dump_raw(item.raw_item)}
            for item in new_items]


def _finish(run_id, trace_path, case, ledger, *, status, answer=None,
            failure_code=None):
    attribution = build_attribution(
        ledger.step_records(case.mode),
        {"latency_ms": case.latency_ms, "price_table": case.price_table})
    return results.assemble_result(
        run_id=run_id, trace_path=trace_path, case_id=case.case_id,
        mode=case.mode, status=status, answer=answer,
        failure_code=failure_code, model_steps=ledger.model_steps,
        tokens_used=ledger.tokens_used,
        tool_invocations=ledger.tool_invocations, attribution=attribution)


def _run_direct(case, run_id, trace_path):
    ledger = RunLedger(case.max_steps, case.max_tokens)
    call = case.direct_call
    tool_name = call["tool"]
    if tool_name not in ("lookup_order", "lookup_shipment"):
        write_native_trace(trace_path, [{
            "item_type": "direct_invocation",
            "raw_item": {"tool": tool_name, "error": "UNKNOWN_TOOL"},
        }])
        return _finish(run_id, trace_path, case, ledger, status="FAILED",
                       failure_code="UNKNOWN_TOOL")
    validator = Draft202012Validator(_tool_schema(tool_name))
    if not validator.is_valid(call["arguments"]):
        write_native_trace(trace_path, [{
            "item_type": "direct_invocation",
            "raw_item": {"tool": tool_name, "error": "INVALID_TOOL_ARGUMENTS"},
        }])
        return _finish(run_id, trace_path, case, ledger, status="FAILED",
                       failure_code="INVALID_TOOL_ARGUMENTS")
    arguments = deepcopy(call["arguments"])
    ledger.record_tool(tool_name)
    try:
        output = asyncio.run(_invoke_direct(case, tool_name, arguments))
    except MappedFailure as failure:
        failure_code = failure.failure_code
        output = None
    except Exception:
        failure_code = "TOOL_EXECUTION_FAILED"
        output = None
    else:
        order_id = output.get("order_id")
        status_value = output.get("status")
        if type(order_id) is not str or type(status_value) is not str:
            raise MappingError("lookup_order returned an invalid observation")
        write_native_trace(trace_path, [{
            "item_type": "direct_invocation",
            "raw_item": {"tool": tool_name, "arguments": arguments,
                         "output": output},
        }])
        return _finish(run_id, trace_path, case, ledger, status="SUCCEEDED",
                       answer=f"Order {order_id} status is {status_value}.")
    write_native_trace(trace_path, [{
        "item_type": "direct_invocation",
        "raw_item": {"tool": tool_name, "error": failure_code},
    }])
    return _finish(run_id, trace_path, case, ledger, status="FAILED",
                   failure_code=failure_code)


async def _invoke_direct(case, tool_name, arguments):
    """Direct invocation sharing the M1 fake-tool replay boundary."""
    try:
        return await asyncio.wait_for(
            _fixture_invoke(
                case.fake_tools["orders" if tool_name == "lookup_order"
                                else "shipments"][arguments[_argument_key(tool_name)]],
                f"{tool_name} {arguments[_argument_key(tool_name)]}")(),
            timeout=TOOL_TIMEOUT_MS / 1000)
    except TimeoutError as error:
        raise ToolTimeoutFailure(f"{tool_name} timed out") from error
    except Exception as error:
        raise ToolExecutionFailure(f"{tool_name} failed: {error}") from error


def run_case(case_id, trace_path, *, turns=None):
    """Run one parity case through the SDK machinery (offline, scripted).

    ``turns`` optionally replaces the scripted model turns (test seam for
    SDK-mechanics proofs). Returns the M1-schema result dict. Domain
    failures come back as FAILED results; unknown cases and
    non-taxonomy SDK errors raise (tooling failure).
    """
    case = load_case(case_id)
    run_id = str(uuid4())
    if case.mode == "direct":
        return _run_direct(case, run_id, trace_path)
    ledger = RunLedger(case.max_steps, case.max_tokens)
    scripted = ScriptedAgentModel(
        list(case.turns) if turns is None else list(turns), ledger)
    provider = ScriptedModelProvider(scripted)
    agent = Agent(
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=list(build_function_tools(case, ledger).values()),
        model=scripted,
    )
    run_config = RunConfig(
        model=scripted,
        model_provider=provider,
        tracing_disabled=True,
    )
    try:
        result = Runner.run_sync(
            agent,
            case.request,
            max_turns=case.max_steps,
            run_config=run_config,
        )
    except Exception as error:  # noqa: BLE001 - taxonomy boundary
        failure_code = classify_run_exception(error)
        if failure_code is None:
            raise
        write_native_trace(trace_path, [{
            "item_type": "run.failed",
            "raw_item": {"error_type": type(error).__name__,
                         "failure_code": failure_code},
        }])
        return _finish(run_id, trace_path, case, ledger, status="FAILED",
                       failure_code=failure_code)
    answer = result.final_output
    if type(answer) is not str or not answer:
        raise MappingError("The SDK run did not produce a string final output")
    raw_tokens = sum(response.usage.input_tokens + response.usage.output_tokens
                     for response in result.raw_responses)
    if raw_tokens != ledger.tokens_used or len(result.raw_responses) != ledger.model_steps:
        raise MappingError("Scripted usage and SDK usage accounting disagree")
    write_native_trace(trace_path, _run_item_records(result.new_items))
    return _finish(run_id, trace_path, case, ledger, status="SUCCEEDED",
                   answer=answer)
