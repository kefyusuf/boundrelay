# D-015 — M4 Durable State and Recovery

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

M3 is integrated and certified on main. The roadmap's next lesson concerns run state separate from user-facing history, checkpoints, resume versus retry, cancellation, replay from a prior step, and revision-bound evidence. M0–M3 deliberately deferred persistence, checkpoints, recovery, and cancellation to this milestone.

M4 should isolate durability concerns without adding real storage engines, distributed coordination, timeouts, side effects, or approval semantics. M3 already provides independent read-only workers, bounded execution, explicit partial failure, and a single synthesis owner; reusing its worker set lets the lesson change only what durability changes.

## Decision

Teach durability through the offline `order-brief-recovery` scenario, reusing the three M3 order-brief workers, their outputs, and their bounded-executor rules unchanged. Add deterministic `crash_after`, `cancel_before`, and `tampered_state` fixture controls.

Keep user-facing history (JSONL trace, result line) append-only and never read it back for recovery. Keep one engine-owned, schema-validated run-state document per run under a caller-provided state directory, with immutable per-step checkpoint snapshots, atomic writes, and a canonical-JSON digest. Loading state fails closed on version, schema, binding, or digest mismatch, with zero worker invocations.

Checkpoint every step terminal before the next admission. On resume, recorded `SUCCEEDED` and `FAILED` outcomes are never re-executed; only a worker without a recorded terminal is re-executed exactly once. Retry is taught as the naive contrast — a fresh run that re-executes everything — and is not a canonical case. Scripted cancellation is a domain outcome (`CANCELLED`, result line, exit `0`, no failure code) that drains entered workers, checkpoints their terminals, and remains resumable. Replay loads a validated checkpoint into a new run identity and never mutates the source state.

Use exactly six canonical cases in parallel mode: clean completion, crash-resume, crash-resume-partial, cancel-resume, replay-from-checkpoint, and corrupt-state rejection. Extend the trace type enum only with the foundation-declared `checkpoint.saved`, `checkpoint.restored`, and `run.cancelled`; the envelope stays at version `1.0`.

Reuse the unchanged shared event envelope and step/run event types. Validate raw traces, multi-phase process flows, and normalized state documents before semantic comparison. Prove durability with real subprocess exits, on-disk tampering, and interrupted-write artifacts — not runtime self-report.

## Consequences

- M4 remains lesson-local, framework-free, offline, and TypeScript/Python-first.
- The run-state document and its digest are new shared contracts specific to this scenario.
- A crash can lose at most the in-flight step, never a recorded terminal.
- Recorded failures are evidence, not pending work; resume never re-runs them.
- `CANCELLED` joins the domain status set without weakening the M3 failure taxonomy.
- The future M4 authority invokes M3, retaining the M3→M2→M1→M0 chain and current-revision evidence checks.
- Real storage engines, distributed state, multi-run locking, timeouts/forced termination, automatic failure re-execution, `UNKNOWN` outcomes, approval/idempotency, real providers, Go, MCP, framework mappings, and shared-runtime extraction remain outside M4; M5 owns side-effect semantics.

## Design

[M4 Durable State and Recovery Design](../superpowers/specs/2026-11-01-m4-durable-state-recovery-design.md)

## Acceptance gate

The owner approved the written design and this decision on 2026-11-01. Detailed implementation planning is the next artifact; reviewed-plan approval and execution-method selection are required before product implementation. No lower-milestone boundary is changed by this decision.
