# Lesson 01 — Bounded Single-Agent Tool Loop

## Problem

A caller can ask a simple factual question such as `Show order ORD-1001 status.`, or a question that needs more than one observation such as `Why is order ORD-1001 delayed?`.

The first case should not become an agent loop. A direct typed function call is sufficient. The second case can justify a bounded model–tool–observation loop because the shipment identifier is only known after the order lookup returns.

This lesson implements both paths in TypeScript and Python against the same canonical scenario, schemas, fake model trajectories, fake read-only tools, budgets, and observable event contract.

## Success criteria

A correct Lesson 01 implementation must satisfy all accepted M1 invariants:

- direct mode invokes `lookup_order` without invoking a model;
- agent mode follows the canonical `lookup_order -> lookup_shipment -> final` trajectory;
- only `lookup_order` and `lookup_shipment` are registered, and both are `READ_ONLY`;
- outer model-turn validation does not enumerate tool names, so registry lookup owns `UNKNOWN_TOOL`;
- invalid tool arguments fail before dispatch;
- timeout and tool execution failure are single-attempt failures;
- a tool call on the final permitted model turn is rejected before dispatch;
- a model turn that pushes token usage over the limit cannot dispatch a tool or become a successful final answer;
- exact budget equality remains valid;
- every result and event validates against the shared JSON Schemas;
- TypeScript and Python produce equivalent normalized results and traces for all eight canonical cases;
- verification evidence is bound to the exact candidate Git revision.

## Deterministic baseline

When the operation and identifier are already known, use the direct function boundary:

```text
Show order ORD-1001 status.
        |
        v
lookup_order({order_id: "ORD-1001"})
        |
        v
Order ORD-1001 status is SHIPPED.
```

TypeScript:

```bash
npm --prefix lessons/01-bounded-tool-loop/typescript run run -- \
  --mode direct \
  --case direct-order-status \
  --trace "$PWD/.boundrelay/manual/m1-ts-direct.jsonl"
```

Python:

```bash
PYTHONPATH=lessons/01-bounded-tool-loop/python/src \
python -m boundrelay_m1 \
  --mode direct \
  --case direct-order-status \
  --trace "$PWD/.boundrelay/manual/m1-py-direct.jsonl"
```

Direct mode consumes zero model steps and zero model tokens.

## Reason to introduce model judgment

The bounded loop is useful when the next operation depends on an observation that is not yet available.

For the canonical investigation:

```text
Why is order ORD-1001 delayed?
        |
        v
model decision: lookup_order
        |
        v
observation: shipment_id = SHP-1001
        |
        v
model decision: lookup_shipment
        |
        v
observation: reason = WEATHER
        |
        v
model decision: final
```

The model does not own dispatch, budget enforcement, validation, retries, persistence, or side effects. M1 uses a deterministic scripted model provider so the orchestration contract can be verified offline.

## Naive implementation

A naive loop trusts a model-shaped response and dispatches immediately:

```typescript
const turn = await model.nextTurn(input);
const tool = registry.resolve(turn.decision.tool);
const output = await tool!.invoke(turn.decision.arguments);
```

```python
turn = await model.next_turn(...)
tool = registry.resolve(turn["decision"]["tool"])
output = await tool.invoke(turn["decision"]["arguments"])
```

This collapses distinct trust boundaries. An unknown tool, malformed arguments, exhausted budget, timeout, or malformed model response can reach execution before deterministic code has accepted the decision.

## Failure injection

The canonical scenario contains six bounded agent failures:

| Case | Expected failure | Dispatch rule |
|---|---|---|
| `agent-unknown-tool` | `UNKNOWN_TOOL` | no tool dispatch |
| `agent-invalid-arguments` | `INVALID_TOOL_ARGUMENTS` | no tool dispatch |
| `agent-tool-timeout` | `TOOL_TIMEOUT` | one attempted invocation |
| `agent-tool-failure` | `TOOL_EXECUTION_FAILED` | one attempted invocation |
| `agent-step-budget` | `STEP_BUDGET_EXCEEDED` | first tool succeeds; rejected second call is not dispatched |
| `agent-token-budget` | `TOKEN_BUDGET_EXCEEDED` | first tool succeeds; over-budget second turn is not dispatched |

There is no automatic retry in M1.

## Corrected implementation

The accepted agent state machine uses this order for every model turn:

1. reject before a model request if no model turn remains;
2. emit `model.requested`, count the turn, and obtain the provider response;
3. emit a JSON-safe `model.completed`;
4. validate the outer model-turn shape;
5. count reported token usage and emit `budget.consumed`;
6. reject if cumulative tokens exceed the limit;
7. accept a valid final answer immediately;
8. for a tool call, resolve the registry entry;
9. validate tool-specific arguments;
10. reject a continuation tool call when the current turn is the final permitted model turn;
11. emit `tool.requested`, invoke exactly once through the runtime-owned timeout boundary, and emit `tool.completed` or `tool.failed`;
12. pass only the structured observation into the next model turn.

The canonical successful case uses exactly three model turns and exactly 129 reported tokens. Equality with those limits is valid.

## Verification evidence

Install both lesson runtimes and run the sole M1 authority command:

```bash
python -m pip install -e lessons/00-workflow-or-agent/python
python -m pip install -e lessons/01-bounded-tool-loop/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
npm ci --prefix lessons/01-bounded-tool-loop/typescript
python scripts/verify_m1.py
```

The gate first runs the existing M0 authority as a regression check. It then runs M1 contracts, TypeScript checks, Python checks, verifier-safety tests, and the cross-language parity verifier.

A passing exact-revision run writes:

```text
.boundrelay/m1/verification-evidence.json
.boundrelay/m1/traces/
```

The central verifier executes all eight canonical case/mode pairs in both languages. It validates result/event schemas, case/mode/trace binding, run IDs, event sequences, terminal state, dispatch boundaries, budget semantics, and normalized result/trace equality.

Evidence is written only after a second clean-worktree check confirms that `HEAD` is unchanged.

## Trade-offs

| Dimension | Direct function call | Bounded tool loop |
|---|---|---|
| Control flow | Explicit and fixed | Observation-dependent |
| Model cost | None | Present with a real provider |
| Latency | One local/tool boundary | Multiple model/tool turns |
| Auditability | Simple call/result | Requires full trace and budget evidence |
| Failure surface | Tool validation/execution | Adds malformed decisions and model budgets |
| Best fit | Known operation + known identifier | Next operation depends on prior observations |

The loop buys controlled adaptability at the cost of more state transitions and more failure modes.

## When not to use this pattern

Do not use the agent loop when the caller already knows the exact operation and identifier, when a deterministic workflow can derive the next step reliably, when the environment cannot tolerate model latency or cost, or when policy requires a fixed rule path.

Do not add mutating tools, retries, persistence, approval, idempotency, multi-agent routing, Go parity, MCP adapters, or real provider integration to this lesson. Those are later milestones with separate boundaries.

## Exercises

1. Add a new invalid identifier fixture and confirm argument validation fails before `tool.requested`.
2. Change the successful case token limit from `129` to `128` and observe the final turn fail with `TOKEN_BUDGET_EXCEEDED`.
3. Change the successful case step limit from `3` to `2` and observe the shipment call get rejected before dispatch.
4. Add a malformed outer model turn and confirm its reported usage is not counted.
5. Compare the direct and agent traces and identify which events exist only because model judgment was introduced.
