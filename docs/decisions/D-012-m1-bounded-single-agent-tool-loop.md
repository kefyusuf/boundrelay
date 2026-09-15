# D-012 — M1 Bounded Single-Agent Tool Loop

- **Status:** Proposed
- **Date:** 2026-09-15

## Decision

M1 will teach one bounded single-agent tool loop through the `order-investigation` scenario using TypeScript and Python, a deterministic offline scripted model, and exactly two registered read-only tools: `lookup_order` and `lookup_shipment`.

The orchestration runtime owns model-turn validation, tool allow-list enforcement, per-tool argument validation, dispatch, timeout enforcement, model-step accounting, provider-reported token accounting, terminal state, and observable evidence. Model output is untrusted structured input and cannot invoke a tool directly.

The direct-function baseline remains first-class: requests whose operation and identifier are already known bypass the model. Agent mode is used only when an observation must inform a later decision.

M1 uses hard step and token budgets and fails closed. Unknown tools, invalid arguments, tool timeout, tool execution failure, step-budget exhaustion, and token-budget exhaustion terminate explicitly. Automatic retries are not permitted in M1.

All M1 tools are `READ_ONLY`. Side effects, idempotency, approval, persistence/recovery, multi-agent topology, real providers, Go, MCP, and framework adapters remain outside M1.

## Consequences

- The shared event envelope stays at schema version `1.0` and gains tool and budget event types already reserved by the foundation design.
- M1 receives its own result contract instead of reusing M0 routing-specific result fields.
- TypeScript and Python must converge on the same normalized model/tool/budget behavior and failure boundaries.
- Deterministic fake-model usage metadata is the M1 token-accounting authority; M1 does not add a tokenizer dependency.
- A tool request on the last permitted model step is rejected before dispatch because no subsequent model turn remains to consume the observation.
- Timeout and tool failure are single-attempt failures; retry semantics are intentionally deferred.
- M1 completion requires exact-revision verification evidence and must not regress M0.

## Design

`docs/superpowers/specs/2026-09-15-m1-bounded-tool-loop-design.md`

## Approval gate

This decision remains **Proposed** until the written M1 design is reviewed and explicitly accepted by the human project owner. Implementation planning must not begin before that approval.
