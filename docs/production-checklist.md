# Production Checklist

Every claim below is linked to the gate and invariant/matrix identifiers that prove it for the current revision; the linkage is enforced by `tools/contracts/test_v1_checklist.py` (each referenced gate file and identifier must exist). Residual gaps — the things a real production deployment would still need beyond BoundRelay's offline, deterministic scope — are listed at the end and are deliberately not claimed as proven.

Proof columns: `Gate` = the `scripts/verify_m*.py` authority whose PASSED evidence covers the claim; `Proof ids` = invariant identifiers (`M<N>-nn` from each lesson's `invariants.yaml`), failure-matrix rows (`M<N>-F<n>` from `fixtures/failure-matrix.yaml`), or probe names.

## State

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-S1 | Run state is a closed, schema-validated document with SHA-256 digest and atomic writes; truncated files never load | scripts/verify_m4.py | M4-02, M4-03, M4-F3 |
| V1-S2 | Run state is the only recovery authority; user-facing history is never read back | scripts/verify_m4.py | M4-01 |
| V1-S3 | State loading fails closed on version/schema/binding/digest mismatch with zero worker invocations | scripts/verify_m4.py | M4-04, M4-F3 |
| V1-S4 | Cancellation is a domain outcome (result line, exit 0, no failure code) and remains resumable | scripts/verify_m4.py | M4-11, M4-12, M4-F4 |

## Recovery

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-R1 | A crash loses at most the in-flight step, never a recorded terminal (write-ahead checkpoints) | scripts/verify_m4.py | M4-02, M4-F1 |
| V1-R2 | Recorded outcomes are never re-executed on resume; in-flight re-executes exactly once | scripts/verify_m4.py | M4-05, M4-06, M4-07, M4-F1 |
| V1-R3 | Replay seeds a new run from a validated checkpoint and never mutates the source | scripts/verify_m4.py | M4-14 |
| V1-R4 | An unprovable side effect keeps the run UNKNOWN — never flattened into success or failure | scripts/verify_m5.py | M5-F3 |

## Side effects

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-E1 | Effects are submitted at most once per deterministic idempotency key; duplicates adopt the original outcome | scripts/verify_m5.py | M5-F4 |
| V1-E2 | The submit→confirm window is the only unsafe window, guarded by a write-ahead submit marker | scripts/verify_m5.py | M5 crash rows (M5-F2) |
| V1-E3 | A submit-window crash resolves by key lookup without re-submission (reconciled) | scripts/verify_m5.py | M5-F2 resolution phase |
| V1-E4 | Audit is append-only and never consulted for recovery decisions | scripts/verify_m5.py | M5 audit invariants |

## Permissions

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-P1 | No effect submission without a granted approval bound to (operation, order, payload digest) | scripts/verify_m5.py | M5-F1 |
| V1-P2 | Approval rejection terminates with zero submissions and an audit record | scripts/verify_m5.py | M5-F1 |
| V1-P3 | Irreversible actions are gated before execution, not reconciled after | scripts/verify_m5.py | M5 approval invariants |

## Observability

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-O1 | Every canonical case's event surface matches its declared contract (fail-closed audit) | scripts/verify_m6.py | M6 event-surface audit |
| V1-O2 | Deterministic attribution (clock-injected latency, fixture-priced cost, attempt reconciliation) on every run result | scripts/verify_m6.py | M6 attribution invariants |
| V1-O3 | Golden trajectories pin behavior for all cases; three languages where ported | scripts/verify_m7.py | M6/M7 golden parity |
| V1-O4 | Shared JSONL traces are schema-valid, inspectable via the offline trace inspector, and normalized for cross-language comparison | scripts/verify_m6.py | M0–M5 trace contracts; inspector probes (tools/parity/test_v1_inspector.py) |

## Evaluation

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-V1 | An independent evaluator compares every case against goldens and fails closed on divergence | scripts/verify_m6.py | evaluator probes |
| V1-V2 | Every declared failure class is proven live (chaos replay) with stable identifiers | scripts/verify_m6.py | M0-F1…M5-Fn |
| V1-V3 | Regressions are reviewable as diffs (goldens regenerate only via a reviewed command) | scripts/verify_m6.py | regenerate guard |

## Cost controls

| ID | Claim | Gate | Proof ids |
|---|---|---|---|
| V1-C1 | Per-step cost and latency are attributed deterministically from fixture tables; totals equal the sum | scripts/verify_m6.py | M6 attribution |
| V1-C2 | Model-step and token budgets are hard limits that fail closed | scripts/verify_m1.py | M1 budget invariants |
| V1-C3 | Cost visibility is offline and deterministic; no real-cost APIs are claimed | scripts/verify_m6.py | M6 exclusions |

## Residual gaps (deliberately unproven in this scope)

- Multi-process coordination, distributed locking, and real storage engines (single-run, file-backed only).
- Real providers and real cost APIs (D-006 keeps every lesson offline with deterministic fakes).
- Network-level retries and timeouts (deferred with M5's exclusions; scripted controls only).
- Go ports beyond M0/M3 (P4) and framework mappings beyond LangGraph×M3 (P5).
- Human-in-the-loop approval services (the approver is a scripted fixture decision).
