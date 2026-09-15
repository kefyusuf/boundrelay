# M1 Bounded Single-Agent Tool Loop Design

- **Date:** 2026-09-15
- **Status:** Accepted
- **Milestone:** M1 — Bounded single-agent tool loop
- **Project:** BoundRelay (`boundrelay`)
- **Depends on:** Foundation design, D-001 through D-011, completed M0 behavioral-parity slice

## 1. Purpose

M1 introduces the smallest useful agent loop after M0 proved deterministic routing, fail-closed model decisions, shared traces, and TypeScript/Python parity.

The lesson teaches one model-backed agent that can choose between a final answer and one of two read-only tools. The orchestration runtime, not the model, owns tool registration, argument validation, dispatch, timeouts, step limits, token limits, terminal state, tracing, and failure policy.

M1 must preserve BoundRelay's first-principles teaching rule: a direct function call remains the preferred solution when the operation and identifier are already known. The agent loop is introduced only for a request that requires interpreting an observation before deciding the next action.

## 2. Teaching scenario

The canonical scenario is **order investigation**.

Two read-only tools are available:

- `lookup_order(order_id)` — returns order status and, when present, a shipment identifier.
- `lookup_shipment(shipment_id)` — returns shipment status and delay information.

The deterministic baseline handles a request such as `Show order ORD-1001 status` by calling `lookup_order` directly. It does not invoke a model.

The agent case handles a request such as `Why is order ORD-1001 delayed?` through a bounded loop:

```text
request
  -> model turn
  -> validated lookup_order call
  -> order observation
  -> model turn
  -> validated lookup_shipment call
  -> shipment observation
  -> model turn
  -> final answer
```

The canonical success records are:

```text
ORD-1001 -> status=SHIPPED, shipment_id=SHP-1001
SHP-1001 -> status=DELAYED, reason=WEATHER
```

The canonical success answers are:

```text
direct: Order ORD-1001 status is SHIPPED.
agent:  Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.
```

This scenario is intentionally narrow. It is large enough for an observation to influence a later decision but small enough that every transition can be inspected and verified.

## 3. Scope

### Included

- lesson `lessons/01-bounded-tool-loop/`;
- TypeScript and Python implementations;
- direct-function baseline plus single-agent mode;
- deterministic offline fake model trajectories;
- deterministic offline fake read-only tools;
- structured model-turn and tool-argument contracts;
- explicit tool registry;
- exact tool allow-list enforcement;
- hard model-step budget;
- hard aggregate token budget;
- runtime-owned per-tool timeout;
- unknown-tool rejection;
- malformed-tool-argument rejection;
- tool timeout and tool execution failure;
- JSONL events for model, tool, budget, and run behavior;
- cross-language normalized parity;
- revision-bound M1 verification evidence.

### Explicitly excluded

- real model providers;
- Go implementation;
- side-effecting or mutating tools;
- retries and backoff;
- idempotency keys;
- persistence or checkpoints;
- human approval;
- multi-agent routing or handoff;
- parallel execution;
- MCP;
- framework adapters;
- reusable general-purpose runtime extraction;
- UI or trace viewer changes.

The excluded items remain future milestones. In particular, M1 must not pre-implement M4 recovery or M5 side-effect semantics.

## 4. Canonical cases

M1 defines exactly eight milestone-level parity cases.

| Case ID | Mode | Purpose | Expected result |
|---|---|---|---|
| `direct-order-status` | `direct` | Prove an agent is unnecessary when the operation is known | `SUCCEEDED` |
| `agent-delayed-shipment` | `agent` | Normal two-tool observation loop | `SUCCEEDED` |
| `agent-unknown-tool` | `agent` | Model names an unregistered tool | `FAILED / UNKNOWN_TOOL` |
| `agent-invalid-arguments` | `agent` | Known tool receives schema-invalid arguments | `FAILED / INVALID_TOOL_ARGUMENTS` |
| `agent-tool-timeout` | `agent` | Registered tool does not complete before its deadline | `FAILED / TOOL_TIMEOUT` |
| `agent-tool-failure` | `agent` | Registered tool raises a deterministic execution error | `FAILED / TOOL_EXECUTION_FAILED` |
| `agent-step-budget` | `agent` | Model requests another tool on its last permitted turn | `FAILED / STEP_BUDGET_EXCEEDED` |
| `agent-token-budget` | `agent` | Cumulative provider-reported usage exceeds the token limit | `FAILED / TOKEN_BUDGET_EXCEEDED` |

Other malformed model envelopes may be rejected as `INVALID_MODEL_DECISION` and covered by contract/unit tests, but they are not a ninth milestone parity trajectory.

## 5. Architecture

M1 keeps orchestration deterministic around a bounded model decision boundary.

```text
                         +-------------------+
request ----------------> orchestration loop |
                         +---------+---------+
                                   |
                           model request (N)
                                   |
                                   v
                         +-------------------+
                         | scripted model    |
                         +---------+---------+
                                   |
                              model turn
                                   |
                                   v
                     +-------------------------+
                     | outer schema validation |
                     +------------+------------+
                                  |
                                  v
                     +-------------------------+
                     | token-budget accounting |
                     +------------+------------+
                                  |
                         final or tool_call
                                  |
                 +----------------+----------------+
                 |                                 |
               final                            tool_call
                 |                                 |
        terminal success                   known-tool check
                                                   |
                                          argument schema check
                                                   |
                                      continuation-budget check
                                                   |
                                          timeout-bound dispatch
                                                   |
                                            tool observation
                                                   |
                                                   +----> next model turn
```

The model cannot invoke a function directly. It produces untrusted structured data. The runtime validates that data before any dispatch.

## 6. Canonical model-turn contract

A model turn has two layers: a decision and usage metadata.

```json
{
  "schema_version": "1.0",
  "decision": {
    "kind": "tool_call",
    "call_id": "call-1",
    "tool": "lookup_order",
    "arguments": {"order_id": "ORD-1001"}
  },
  "usage": {
    "input_tokens": 42,
    "output_tokens": 18
  }
}
```

or:

```json
{
  "schema_version": "1.0",
  "decision": {
    "kind": "final",
    "answer": "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather."
  },
  "usage": {
    "input_tokens": 55,
    "output_tokens": 14
  }
}
```

The outer model-turn schema validates shape, decision kind, call identifier, non-empty tool name, object arguments, non-empty final answer, and non-negative integer usage values.

The outer schema deliberately does **not** enumerate tool names. This preserves a distinct `UNKNOWN_TOOL` boundary: an unknown tool may be a structurally valid model decision but must fail registry lookup before dispatch.

## 7. Tool registry and argument contracts

The runtime owns an explicit registry containing only:

```text
lookup_order
lookup_shipment
```

Both tools are classified `READ_ONLY`.

Each registered tool has:

- a stable name;
- a tool-specific JSON Schema for arguments;
- a side-effect class (`READ_ONLY` in M1);
- a runtime-owned timeout;
- an implementation function.

The canonical argument contracts are:

```json
{"order_id": "ORD-1001"}
```

and:

```json
{"shipment_id": "SHP-1001"}
```

`order_id` must match `^ORD-[0-9]{4}$`. `shipment_id` must match `^SHP-[0-9]{4}$`. Each argument object rejects additional properties and requires exactly its identifier field. These rules are shared by TypeScript and Python through JSON Schema rather than duplicated language-specific parsing rules.

Tool observations are structured JSON objects and are passed back to the next model turn as explicit context. They do not contain hidden reasoning.

## 8. Validation and dispatch order

For agent mode, the runtime must apply this order:

1. Before a model request, if `model_steps >= max_steps`, fail with `STEP_BUDGET_EXCEEDED` rather than starting another turn.
2. Request the next model turn and increment `model_steps` once for that invocation.
3. Validate the model-turn envelope.
4. Add provider-reported token usage to the aggregate token counter.
5. If the aggregate exceeds `max_tokens`, fail before accepting the decision or dispatching a tool.
6. If the decision is `final`, complete successfully.
7. If the decision is `tool_call`, resolve the tool in the registry.
8. Reject an unknown tool before argument validation or execution.
9. Validate arguments against that tool's schema.
10. If `model_steps >= max_steps`, reject the tool call with `STEP_BUDGET_EXCEEDED` before execution because no later turn remains to consume its observation.
11. Execute the tool through the timeout boundary.
12. Add the observation to explicit loop context and continue to the next model turn.

No failure path may silently fall back to another tool, coerce arguments, invent missing identifiers, or continue after a hard budget failure.

## 9. Step-budget semantics

`max_steps` counts **model turns**, not tool calls.

A model invocation consumes one step. A final answer is valid on the last permitted step. A tool request on the last permitted step is not executed because the loop would have no remaining model turn to observe the result and terminate coherently.

Example with `max_steps = 3`:

```text
step 1 -> lookup_order      allowed
step 2 -> lookup_shipment   allowed
step 3 -> final             allowed
```

but:

```text
step 1 -> lookup_order      allowed
step 2 -> lookup_shipment   allowed
step 3 -> lookup_order      STEP_BUDGET_EXCEEDED; rejected call is not dispatched
```

Equality at the limit is allowed for a final answer. A model request is never started after the limit has already been consumed.

## 10. Token-budget semantics

M1 uses provider-reported usage from each valid model turn. It does not introduce a tokenizer dependency or estimate tokens from text.

For offline mode, fake-model fixtures provide deterministic `input_tokens` and `output_tokens` values. The runtime accumulates:

```text
tokens_used += input_tokens + output_tokens
```

After each validated model turn, if `tokens_used > max_tokens`, the runtime emits budget failure and rejects that turn's requested action. No tool is dispatched and no final answer from the over-budget turn is accepted.

`tokens_used == max_tokens` is valid.

A later real-provider mapping may adapt provider usage metadata into this contract without changing M1 semantics.

## 11. Timeout and tool-failure semantics

Timeout enforcement belongs to the orchestration runtime, not to the model and not to business logic inside a tool.

The scripted timeout fixture represents a tool invocation that never completes on its own. TypeScript and Python must apply their runtime timeout boundary and converge on `TOOL_TIMEOUT`. Exact elapsed milliseconds are not parity-significant.

A deterministic scripted tool exception converges on `TOOL_EXECUTION_FAILED`.

M1 performs **no automatic retry** for either condition. This prevents retry semantics from leaking forward from later milestones and makes one tool decision correspond to at most one actual tool invocation.

## 12. Result contract

M1 uses a dedicated result contract rather than forcing M0 routing-specific fields into a generic shape.

A result contains at least:

```json
{
  "schema_version": "1.0",
  "run_id": "run-...",
  "scenario_id": "order-investigation",
  "case_id": "agent-delayed-shipment",
  "mode": "agent",
  "status": "SUCCEEDED",
  "answer": "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
  "failure_code": null,
  "model_steps": 3,
  "tokens_used": 129,
  "tool_invocations": 2,
  "trace_path": ".boundrelay/m1/...jsonl"
}
```

Success requires a non-empty answer and `failure_code: null`. Failure requires `answer: null` and one explicit failure code. The failure-code set includes the six canonical M1 failures plus `INVALID_MODEL_DECISION` for fail-closed contract rejection. `UNKNOWN` is not used in M1 because all tools are read-only and no external side effect can become indeterminate.

## 13. Event model

The existing event envelope and `schema_version: "1.0"` remain unchanged. M1 extends the allowed event types with event families already reserved by the foundation design:

- `tool.requested`;
- `tool.completed`;
- `tool.failed`;
- `budget.consumed`;
- `budget.exceeded`.

Existing M0 traces remain schema-valid after the enum expansion.

Observable event data must make it possible to verify:

- model-turn sequence;
- decision kind;
- tool name and call identifier;
- validated dispatch boundaries;
- one requested tool maps to at most one execution;
- tool success versus timeout/failure;
- cumulative step and token consumption;
- budget type and limit when exceeded;
- terminal run status and failure code.

Trace data must not record private chain-of-thought.

For `UNKNOWN_TOOL` and `INVALID_TOOL_ARGUMENTS`, no `tool.requested` event is emitted because execution was never authorized. The validated model decision remains visible through `model.completed`, and the run terminates failed.

For timeout or execution failure, one `tool.requested` is followed by one `tool.failed` with the corresponding failure code.

## 14. Deterministic fixtures

Canonical assets remain language-neutral.

M1 adds:

- `fixtures/scenarios/order-investigation.yaml` — cases, modes, budgets, expected outcomes and canonical success answers;
- `fixtures/fake-model/order-investigation.yaml` — ordered model turns and usage values;
- `fixtures/fake-tools/order-investigation.yaml` — order/shipment records plus timeout and failure behaviors;
- `lessons/01-bounded-tool-loop/invariants.yaml` — milestone invariants.

Fake trajectories are ordered lists, not maps keyed only by case. This matters because one case may require several sequential model turns.

The agent runtime must consume exactly the next scripted turn for the requested case. Missing, extra, or out-of-order scripted turns fail deterministically rather than falling back to heuristics.

## 15. Direct baseline

`direct-order-status` exists to prove that agentic control is not the default.

The direct path:

- does not invoke the model;
- does not consume model step or token budget;
- uses the same registered `lookup_order` implementation and timeout boundary;
- emits tool and run events using the common envelope;
- produces the same result schema used by agent mode;
- returns exactly `Order ORD-1001 status is SHIPPED.` for the canonical success fixture.

The lesson documentation must explain why `Show order ORD-1001 status` is a direct function call while `Why is order ORD-1001 delayed?` can justify a bounded loop.

## 16. Cross-language parity

TypeScript and Python may differ internally but must converge on observable behavior.

Parity preserves:

- case ID and mode;
- terminal status;
- failure code;
- normalized event types and order;
- model-step count;
- cumulative token usage;
- tool names and call order;
- tool execution count;
- decision kind;
- budget kind, consumed value, and limit;
- exact canonical final answer for the two success fixtures.

Parity ignores:

- timestamps;
- generated run/event identifiers;
- trace filesystem paths;
- language source identifier;
- stack traces;
- wall-clock timeout duration.

Each trace must have monotonically increasing sequence numbers, one stable run ID, and exactly one terminal run event.

## 17. Verification authority

M1 receives a dedicated local authority command:

```text
python scripts/verify_m1.py
```

The M1 verifier must eventually:

1. require a clean worktree for certification;
2. capture the starting Git revision;
3. run shared contract tests;
4. run TypeScript typecheck/tests;
5. run Python tests;
6. execute all eight canonical cases in both implementations;
7. validate result and event schemas;
8. verify failure-specific no-dispatch/one-dispatch invariants;
9. normalize and compare TypeScript/Python traces;
10. re-check the Git revision and clean worktree immediately before publication;
11. write `.boundrelay/m1/verification-evidence.json` bound to that exact revision.

GitHub Actions must execute the same authority command and publish `.boundrelay/m1/` as revision-bound evidence. M0 verification remains independently runnable and must not regress.

## 18. Required invariants

The implementation plan must encode at least these invariants:

1. Direct mode never calls the model.
2. Agent mode never dispatches a tool before outer decision, registry, and argument validation pass.
3. Only `lookup_order` and `lookup_shipment` are dispatchable in M1.
4. Both tools are read-only and are invoked at most once per accepted call decision.
5. Unknown tools never emit `tool.requested`.
6. Invalid arguments never emit `tool.requested`.
7. Timeout and execution failure each emit exactly one `tool.requested` and one `tool.failed`.
8. A tool call on the final permitted model step is rejected before dispatch.
9. An over-token-budget model turn cannot cause a tool call or successful final answer.
10. No failure path retries automatically.
11. Successful agent investigation follows `lookup_order -> lookup_shipment -> final` for the canonical case.
12. TypeScript and Python produce equivalent normalized behavior.
13. Every run has exactly one terminal event.
14. Verification evidence is bound to the candidate Git revision.

## 19. Planned repository shape

The design intentionally extends the M0 layout rather than extracting a shared runtime prematurely.

```text
contracts/
├── agent/
│   └── model-turn.schema.json
├── tools/
│   ├── lookup-order-arguments.schema.json
│   └── lookup-shipment-arguments.schema.json
├── events/run-event.schema.json          # extend enum, keep envelope v1.0
└── results/
    └── tool-loop-result.schema.json

fixtures/
├── scenarios/order-investigation.yaml
├── fake-model/order-investigation.yaml
└── fake-tools/order-investigation.yaml

lessons/
└── 01-bounded-tool-loop/
    ├── README.md
    ├── invariants.yaml
    ├── typescript/
    └── python/

tools/
└── parity/
    └── verify_m1.py

scripts/
└── verify_m1.py

.github/workflows/
└── m1.yml
```

Exact implementation file names inside the two language directories are selected in the implementation plan; the contracts and behavioral boundaries above are fixed by this design.

## 20. Acceptance criteria

M1 is complete only when all of the following are true for the exact candidate revision:

- the direct baseline succeeds without any model event;
- the normal agent case completes the two-tool trajectory and returns the exact canonical answer;
- all six failure cases terminate with the specified code;
- unknown tool and malformed arguments cause zero actual tool invocations;
- the rejected tool decision on the final permitted model step causes no additional tool invocation;
- an over-token-budget turn causes no post-budget tool dispatch and cannot be accepted as a successful final answer;
- timeout and tool failure each cause exactly one attempted invocation and no retry;
- both implementations emit schema-valid JSONL;
- normalized TypeScript/Python results and traces satisfy the same invariants;
- M0 remains green;
- local and CI verification use the same M1 authority command;
- verification evidence names and records the exact Git revision.

## 21. Acceptance and implementation-planning gate

This design was reviewed and accepted by the human project owner on 2026-09-15.

- D-012 is accepted with the boundaries defined in this document.
- Detailed M1 implementation planning may proceed from this accepted design.
- Any material change to tools, failure taxonomy, budget semantics, side-effect policy, canonical cases, or verification authority must return to the decision gate before implementation continues.
- No M1 implementation code is part of this design change.
