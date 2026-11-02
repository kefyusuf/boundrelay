# D-016 — M5 Idempotent Approved Effects

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

M4 is integrated and certified on main. The roadmap's next lesson concerns idempotency keys, safe retry boundaries, approval before irreversible action, audit records, and an explicit `UNKNOWN` outcome when external reality cannot be proven. M0–M4 deliberately kept every operation read-only and deferred all effect semantics to this milestone.

M5 should isolate effect semantics without adding real networks, payment services, approval UIs, or infrastructure. M4 already provides the durability substrate (typed run state, write-ahead checkpoints, fail-closed resume); M5 adds only what side effects demand on top of it.

## Decision

Teach effects through the offline `order-closure` scenario: the three M3 workers run as unchanged read-only preconditions; one scripted approval decision gates a single mutating step; one idempotent effect submission targets a scripted, file-backed effect ledger; an append-only audit line records attempts and decisions.

Key semantics:

- The idempotency key is derived deterministically (`cancel-and-refund:ORD-1001`), never accepted from model output; the ledger enforces once-per-key and duplicate submissions adopt the original recorded outcome.
- Retries before submission are always safe; the submit→confirm window is the only unsafe window; confirmation-window crashes are resolved by key lookup, adopting the original outcome with `reconciled: true` and never re-submitting a landed effect.
- When reality cannot be proven (lookup unavailable), the run terminates `UNKNOWN` — a domain outcome with a result line and exit `0`, never flattened into `SUCCEEDED` or `FAILED`.
- Approval binds to `(operation, order_id, payload digest)`; no submission without a recorded `granted` approval; rejection ends the run `FAILED` / `APPROVAL_REJECTED` with zero submissions.
- Audit is append-only history and never consulted for recovery decisions.

Use exactly six canonical cases: approval-granted effect-once, approval-rejected no-effect, retry-before-submit, crash-submit-window-resolved, sink-unavailable UNKNOWN, and duplicate-key suppression. The event envelope stays at version `1.0`; the type enum gains only foundation-declared members (`approval.requested/granted/rejected`, tool events for the declared-side-effect step). The run status set gains `UNKNOWN`; the result schema gains `reconciled` and `approval_decision`.

## Consequences

- M5 remains lesson-local, framework-free, offline, and TypeScript/Python-first.
- The effect payload/outcome schema, result schema, and audit schema are new shared contracts specific to this scenario.
- The unprovable window is exactly one step wide; approval and submit markers are checkpointed.
- The future M5 authority invokes M4, retaining the M4→M3→M2→M1→M0 chain and current-revision evidence checks.
- Real networks/services, approval services, transactional outboxes, message queues, distributed locks, model-driven effects, Go, MCP, framework mappings, and shared-runtime extraction remain outside M5.

## Design

[M5 Side Effects, Idempotency, and Human Approval Design](../superpowers/specs/2026-11-02-m5-side-effects-approval-design.md)

## Acceptance gate

The owner approved the written design and this decision on 2026-11-02. Detailed implementation planning is the next artifact; reviewed-plan approval and execution-method selection are required before product implementation. No lower-milestone boundary is changed by this decision.
