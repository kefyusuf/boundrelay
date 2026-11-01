# D-014 — M3 Bounded Read-Only Fan-Out and Fan-In

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

M2 is integrated and certified on main. The roadmap's next lesson concerns independent read-only workers, bounded concurrency, explicit partial failure, deterministic merging, and one synthesizer owning the final output.

M3 should isolate those responsibilities without adding dynamic decomposition, real providers, persistence, recovery, or external writes. M1 already provides a dependent read loop; M2 provides a typed handoff. Neither runtime needs to become a shared orchestration framework for this lesson.

## Decision

Teach the offline `order-brief` scenario through exactly three independent workers: `order-details`, `payment-status`, and `delivery-status`. Every worker receives only the known order ID. The fixed queue and synthesis order follows that list.

Provide sequential mode with one slot and parallel mode with two slots. Invoke each worker once. Collect one validated typed outcome per worker before invoking the deterministic synthesizer. Declared failures remain explicit; malformed payloads never become report facts. Unexpected implementation exceptions remain tooling failures.

The result policy is:

- three successful workers: `SUCCEEDED`, complete brief;
- one or two successful workers: `PARTIAL`, usable sections and explicit missing workers;
- no successful worker: `FAILED` / `ALL_WORKERS_FAILED`, no brief or synthesis call.

The synthesizer is the only business-output publisher, invoked once whenever at least one worker succeeds. The final write is publication into the returned run result, not an external side effect. Completion order cannot affect the business brief.

Use six canonical cases for sequential success, parallel success, out-of-order completion, one declared failure, all declared failures, and one invalid worker output. Keep worker failure codes limited to `WORKER_EXECUTION_FAILED` and `INVALID_WORKER_OUTPUT`.

Reuse the unchanged shared event envelope and step/run event types. Validate raw trace transitions and reconstructed slot bounds before scenario-specific semantic comparison. Distinguish same-mode language parity from cross-mode business equality. Independent gated worker-body tests must prove actual overlap and the concurrency cap; runtime counters or timestamps alone are insufficient.

## Consequences

- M3 remains lesson-local, framework-free, offline, and TypeScript/Python-first.
- Shared worker/result contracts are specific to this scenario.
- Independent missing evidence remains visible; `PARTIAL` cannot be promoted to `SUCCEEDED`.
- Synthesis is deterministic and preserves fixed worker order and failure accounting.
- No global trace sorting or deletion of business fields is needed.
- The future M3 authority invokes M2, retaining the M2→M1→M0 chain and current-revision evidence checks.
- Real models, dynamic topology, retries, deadlines/cancellation, persistence/recovery, external writes, Go, MCP, and shared-runtime extraction remain outside M3.

## Design

[M3 Bounded Fan-Out and Fan-In Design](../superpowers/specs/2026-10-05-m3-bounded-fanout-fanin-design.md)

## Acceptance gate

The owner approved the written design on 2026-10-05. This decision does not supersede or change accepted M0/M1/M2 boundaries. Written-design approval permits detailed implementation planning; reviewed-plan approval and execution-method selection are required before product implementation.
