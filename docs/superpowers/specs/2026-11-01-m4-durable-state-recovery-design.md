# M4 Durable State and Recovery Design

- **Date:** 2026-11-01
- **Status:** Accepted by the owner on 2026-11-01; implementation planning follows
- **Milestone:** M4 — Durable state and recovery
- **Project:** BoundRelay
- **Baseline:** merged M3 at `12f3c59fe5c69bfb4c63464a28001265e9fe9b34`
- **Decision:** [D-015](../../decisions/D-015-m4-durable-state-and-recovery.md), proposed
- **Depends on:** [foundation design](../../design/2026-09-02-foundation-design.md), D-001 through D-014, completed M0/M1/M2/M3 verification

## 1. Purpose and design brief

M4 teaches the difference between what a human inspects and what a runtime depends on. The roadmap requires run state separate from user-facing history, checkpoints, resume versus retry, cancellation, replay from a prior step, and revision-bound evidence.

This proposed design preserves offline execution, TypeScript/Python parity, lesson-local implementations, shared behavioral contracts, and exact-revision evidence. It reuses the M3 order-brief workers unchanged so the lesson isolates durability concerns instead of introducing new business behavior. The proposal does not authorize product implementation; written-design approval, a reviewed implementation plan, and execution-method selection are separate gates.

The teaching objective is:

> A crash must not erase knowledge the runtime already recorded, and a display history must never be mistaken for recoverable state. Durable state is small, typed, validated, and load-bearing; history is append-only and never read back.

M4 adds deterministic crash, cancellation, and corruption controls — not real databases, schedulers, or process supervisors. This follows D-006's offline requirement and the foundation's checkpoint definition: persisted execution state sufficient to resume safely.

## 2. Approaches considered

| Approach | Benefit | Limit | Choice |
|---|---|---|---|
| File-backed typed run state with atomic checkpoints, resume, cancel, and replay | Isolates durability, recovery, and the history/state boundary; offline evidence is repeatable | Does not teach concurrent multi-run coordination or real storage engines | Recommended |
| In-memory state only (M3 status quo) | Simplest runtime | A crash loses everything; cannot teach resume, replay, or the history/state boundary | Rejected for M4 |
| SQLite or an external datastore | Teaches real persistence engineering | Adds a dependency, provider behavior, and nondeterministic failure modes before durability invariants are proved | Defer |
| Rebuilding state by replaying the JSONL trace | One artifact to trust | Makes history load-bearing, blurring the exact boundary this milestone teaches; trace replay cost grows with history | Rejected as a recovery mechanism |

### Teaching sequence

Follow D-005: establish what a crash destroys in an M3-style run, demonstrate the naive response — rerun everything from scratch and show duplicated work with the same results — inject scripted crashes, cancellation, and state corruption, correct the design with a typed checkpointed state document and fail-closed loading, and prove the invariants. The naive example retries every worker in a fresh run after any interruption. The corrected runtime records each step terminal before the next admission and resumes from recorded evidence. The lesson explains when full retry is genuinely the better choice: when recorded state cannot be trusted, when steps are cheaper than recovery logic, and before any step has side effects.

## 3. Canonical scenario: order-brief recovery

The scenario ID is `order-brief-recovery`. It reuses the fixed worker set, canonical outputs, field domains, and order-ID grammar of M3's `order-brief` exactly: `order-details`, `payment-status`, `delivery-status`, each receiving only `{order_id: ORD-1001}`. The three workers remain deterministic, read-only, and invoked at most once per recorded attempt. The M3 worker fixtures are reused; no worker business rule changes.

The new scenario adds three deterministic controls to the fixture grammar:

- `crash_after`: the runner aborts the process after the named step's terminal outcome is durably checkpointed and before the next admission;
- `cancel_before`: the runner stops new admissions before the named worker and drains already-entered work;
- `tampered_state`: a fixture-provided state document that violates its schema, version, binding, or digest, used by the corruption case.

The lesson does not call the M1 tool loop, the M2 router, or the M3 runner as a library; it re-declares the same worker directory lesson-locally, as every lesson does.

## 4. Run state versus user-facing history

Two artifact classes exist and must not be conflated:

- **User-facing history:** the strict JSONL event trace and the single JSON result line. Append-only, inspection-oriented, never read back by the runtime, and never sufficient authority for recovery decisions.
- **Run state:** one engine-owned document per run, validated against a schema, consulted on resume, and authoritative for recovery. It is small, typed, and contains no raw payloads.

The run state document lives under a caller-provided `--state-dir`; the lesson uses a temporary directory per case. Its layout is:

```text
<state-dir>/<run_id>/state.json          current state, rewritten atomically
<state-dir>/<run_id>/checkpoints/step-<sequence>.json   immutable per-step snapshots
```

The current state document contains:

- `state_schema_version: "1.0"`;
- run identity (`run_id`) and binding (`scenario_id`, `case_id`, `execution_mode`, `concurrency_limit`, `requested_order_id`);
- `status`: `RUNNING | SUCCEEDED | FAILED | CANCELLED`;
- `steps`: one record per fixed worker — `worker_id`, `status` (`PENDING | RUNNING | SUCCEEDED | FAILED | CANCELLED`), the validated typed outcome or the fixed failure code, and never a raw rejected payload;
- `sequence_cursor`: the index of the next fixed-queue worker to admit;
- a `digest`: SHA-256 over the canonical JSON of the document body without the digest field.

Checkpoint snapshots are the same document shape at the moment of a step terminal. Writes are atomic: write to a temporary file in the same directory, then rename. A partially written file is never loaded; discovery of one is a tooling failure.

## 5. Checkpoint policy

Every step terminal — success or declared failure — is checkpointed before the next admission. This write-ahead rule means a crash can lose at most the step that was in flight, never a recorded terminal.

`checkpoint.saved` and `checkpoint.restored` events come from the foundation's declared event family. The shared envelope stays at version `1.0`; the type enum gains exactly those foundation-declared members plus `run.cancelled`. No other event types are invented. Event payloads carry only safe identifiers — step name, worker status counts, sequence cursor, and binding fields — never raw payloads or arbitrary exception text.

Loading a state document fails closed. Each of the following is a tooling error (CLI exit `2`, no result line, no worker invocation): missing or unknown `state_schema_version`; schema-invalid documents; digest mismatch; binding mismatch between the state document and the requested case/mode/order; a truncated or partially written file; a referenced snapshot that is missing or fails its own digest check. Corruption is evidence, not a prompt to silently restart.

## 6. Resume versus retry

**Resume** continues the same run from its recorded state:

1. Load and validate `state.json` (fail-closed as above).
2. Emit `checkpoint.restored` with the restored cursor and binding.
3. Re-admit only workers without a recorded terminal, in canonical queue order, under the same bounded-executor rules as M3 (limit 1 sequential, limit 2 parallel).
4. Workers with recorded `SUCCEEDED` or `FAILED` outcomes are never re-invoked; their recorded outcomes flow to synthesis unchanged.
5. The process that completes the run performs exactly one synthesis call after all outcomes have settled, then the single terminal event.

A worker that was in flight when the crash happened has no recorded terminal, so resume re-executes it exactly once. Across the whole run — however many processes it spans — each worker therefore contributes exactly one recorded outcome, and invoked-at-most-once per attempt holds.

**Retry** is the naive contrast: a fresh run with a fresh identity and no `--state-dir` consultation. It re-executes every worker and discards no history because none was consulted. The lesson's walkthrough and unit tests demonstrate retry duplicating all three invocations where resume duplicates none; retry is not a canonical parity case.

A `FAILED` recorded outcome is evidence, not pending work. Resume after all-failed does not re-invoke failed workers and terminates `FAILED` again with identical outcomes.

## 7. Cancellation

A scripted `cancel_before` control stops new admissions before the named worker. Already-entered workers drain normally; their terminals are recorded and checkpointed. The run then emits `run.cancelled`, writes a final checkpoint with `status: CANCELLED` and the workers after the boundary marked `CANCELLED`/`PENDING`, and returns a canonical result — exactly one JSON stdout line, exit `0`.

`CANCELLED` is a domain outcome, distinct from `FAILED` (no failure code) and from tooling errors (exit `2`). A cancelled run is resumable: resume after `CANCELLED` completes only the remaining workers and terminates `SUCCEEDED` or `PARTIAL` according to the M3 success-count table. Cancellation is cooperative and deterministic; there is no timeout-based or forced termination, which remains deferred.

## 8. Replay from a prior step

`--replay-from <checkpoint-path>` loads a validated checkpoint snapshot into a **new** run with a new `run_id`, seeded with the snapshot's recorded outcomes and cursor. The source run's state files are never modified. Replay completes the remaining workers and synthesis exactly as a resume does; the resulting brief is identical to the original run's brief whenever the remaining workers are deterministic. Replay exists for deterministic debugging — re-deriving a later state from an earlier known-good point — and is a domain outcome with the same result semantics as resume.

## 9. Canonical cases

Exactly six canonical cases, all in parallel mode (the mode that makes in-flight loss observable):

| Case ID | Phases | Expected outcome |
|---|---|---|
| `parallel-clean-complete` | one run | `SUCCEEDED`, complete brief, checkpoint after every step, peak 2 |
| `parallel-crash-resume` | crash after payment terminal; resume | Phase 1 exits `2` with durable state and no result line; phase 2 `SUCCEEDED`; order and payment invoked exactly once across both processes |
| `parallel-crash-resume-partial` | crash after delivery declared failure; resume | Resume is `PARTIAL`, delivery missing; the recorded failure is not re-executed |
| `parallel-cancel-resume` | cancel before delivery; resume | Phase 1 `CANCELLED` with delivery pending; resume `SUCCEEDED` with complete brief |
| `parallel-replay-from-checkpoint` | replay from after-order checkpoint | New run completes remaining workers; same brief; source state untouched |
| `parallel-corrupt-state` | resume with tampered state | Tooling error, exit `2`, zero worker invocations, no result line |

The crash boundary is deterministic by construction: the process aborts only after the named terminal is durably checkpointed, so the phase split never depends on timing or interleaving. Unit tests additionally cover crash during the first worker, resume of a `RUNNING`-marked in-flight worker, atomicity of checkpoint writes (interrupted write leaves the previous document loadable), version and binding mismatches, digest tampering of both state and snapshots, retry duplicating work, resume of an all-failed run, and synthesis invoked exactly once by the completing process.

## 10. Run result

The result schema extends the M3 result shape with recovery fields: `status` gains `CANCELLED`; `resumed` (boolean), `restored_cursor`, `restored_worker_ids`, `state_dir`, and `run_state_status` are added; worker outcomes, synthesis invocation, brief, and failure-code semantics stay exactly as M3 defined them.

| Situation | Run status | Result line | Exit |
|---|---|---|---|
| Clean completion | `SUCCEEDED` | yes | `0` |
| Partial completion | `PARTIAL` | yes | `0` |
| All workers failed | `FAILED` / `ALL_WORKERS_FAILED` | yes | `0` |
| Scripted cancellation | `CANCELLED` | yes | `0` |
| Crash control | tooling failure | no | `2` |
| Corrupt/invalid state load | tooling failure | no | `2` |

## 11. Trace contract

The shared event envelope, its version, and all M3 validation rules are unchanged. The type enum gains the foundation-declared `checkpoint.saved`, `checkpoint.restored`, and `run.cancelled`.

- `checkpoint.saved` data: binding fields, `step_name`, `state_status`, `sequence_cursor`.
- `checkpoint.restored` data: binding fields, `restored_cursor`, counts of restored outcome records.
- `run.cancelled` data: binding fields, `cancelled_before` worker ID, fixed code `CANCELLED_BEFORE_STEP`.
- Worker, synthesis, and terminal events keep their M3 payload rules; a resumed run's events carry the same `run_id` as the state document they continue.
- Exactly one terminal run event per completed process phase: `run.completed` for domain completion, `run.failed` for canonical all-failed, `run.cancelled` for cancellation. A crash phase ends with no terminal event — the durable state document is its only testimony.

## 12. Validation, normalization, and parity

Raw-first validation extends M3's rules: strict JSONL, schema-valid envelopes and payloads, contiguous sequences within each process, unique event IDs, exact case/mode/order binding, per-worker lifecycle integrity, slot bounds, complete fan-in before synthesis, and terminal/result agreement. Additionally: every `checkpoint.saved` precedes the next admission; a `checkpoint.restored` appears before any worker start in a resuming process; a resuming process's worker starts cover exactly the workers without recorded terminals; crash phases end without terminals.

Two comparison relations remain distinct:

1. **Same case across languages:** compare normalized results, worker lifecycles (projected per worker across the process boundary), checkpoint/restore/cancellation behavior, and the normalized state document — with `run_id`, paths, timestamps, and runtime metadata canonicalized away. The digest is validated for within-run integrity, not compared across languages, because the body contains generated identity.
2. **Business projection:** order ID, final status, worker outcomes, synthesis invocation, and brief agree between a clean run, a crash-resumed run, a cancel-resumed run, and a replayed run that reach the same worker outcomes. Case IDs, phase structure, and lifecycle events differ and are not part of this comparison.

Mutation tests must reject: a missing `checkpoint.saved`, a restore followed by re-invocation of a recorded worker, a resumed run missing a phase-1 outcome, a `CANCELLED` result with exit `2` or a failure code, a tampered state loading successfully, a crash phase producing a result line, and a replay mutating its source state.

## 13. Proving durability, not self-report

The authority must prove durability with artifacts and processes, not runtime counters:

- a crash phase is a real subprocess exit (`2`) whose state document the next phase loads;
- independent worker-body probes (as in M3) prove that across both phases each worker is invoked exactly the designed number of times — recorded workers zero, in-flight worker once;
- a checkpoint file is mutated on disk by the test harness and the next load must fail closed;
- an interrupted-write test leaves a truncated file and the loader must reject it without corrupting the previous snapshot;
- the replay case asserts the source run's state document is byte-identical before and after.

A bounded test watchdog may detect a hang; it remains test infrastructure, not a runtime timeout feature. No wall-clock durability claim (fsync latency, crash-window size) is an acceptance criterion.

## 14. Planned artifacts and architecture

Lesson-local and idiomatic in each language:

- `lessons/04-durable-state-recovery/{typescript,python}/`: typed state document and validation, atomic checkpoint store, resume/replay loaders, crash/cancel controls, bounded executor (M3 rules), collector and synthesizer (M3 contracts), runner lifecycle, CLI, and tests;
- `lessons/04-durable-state-recovery/{README.md,invariants.yaml}`;
- `contracts/state/order-brief-run-state.schema.json`;
- `contracts/results/order-brief-recovery-result.schema.json`;
- `fixtures/scenarios/order-brief-recovery.yaml` (reusing `fixtures/workers/order-brief/` where valid);
- `tools/contracts/test_m4_contracts.py`;
- `tools/parity/{verify_m4.py,test_m4_verification_safety.py}`;
- `scripts/verify_m4.py` and `.github/workflows/m4.yml`.

No generic persistence framework, no storage engine dependency, no shared-runtime extraction, and no edits to M0–M3 business rules are required. The event-type enum extension is the only shared-contract change, and it adds only foundation-declared members.

## 15. Verification authority and evidence

The documented authority is `python scripts/verify_m4.py`. It captures a clean starting revision before invoking `python scripts/verify_m3.py`, retaining the M3→M2→M1→M0 chain. The gate must run shared contract/fixture checks, TypeScript typecheck/tests, Python tests, multi-phase subprocess cases in both languages, offline/import guards, verifier-safety mutation tests, state-tamper and atomicity probes, all six paired case flows, same-case semantic parity including normalized state documents, and business-projection comparisons. Lower evidence must match the starting revision with PASSED status.

Before any gate step, remove stale M4 evidence. Publish `.boundrelay/m4/verification-evidence.json` only after all checks pass and final clean-worktree/unchanged-HEAD checks succeed. Evidence records the exact revision, command, runtime versions, every phase invocation with its exit code, the six case records, raw trace paths for every phase, and normalized state-document comparisons. Local and CI use the same command; CI checks out the exact candidate commit and uploads `m4-verification-<revision>` including hidden evidence files.

## 16. Invariants and completion criteria

1. Run state is the only recovery authority; traces and results are never read back to reconstruct it.
2. Every step terminal is checkpointed before the next admission.
3. Checkpoint writes are atomic; a truncated file is never loaded.
4. State loading fails closed on version, schema, binding, or digest mismatch — with zero worker invocations.
5. Recorded `SUCCEEDED` outcomes are never re-executed on resume.
6. Recorded `FAILED` outcomes are never re-executed on resume.
7. A worker without a recorded terminal is re-executed exactly once on resume.
8. Each worker contributes exactly one recorded outcome to the merged run, however many processes it spans.
9. Resume preserves case/mode/order binding; a mismatched resume is a tooling error.
10. Retry is a fresh run and re-executes every worker; it consults no durable state.
11. Cancellation stops admission, drains entered workers, records and checkpoints their terminals before terminating.
12. `CANCELLED` is a domain outcome: result line, exit `0`, no failure code.
13. Resume after `CANCELLED` completes only the remaining workers.
14. Replay seeds a new run identity and never mutates the source state.
15. Exactly one synthesis call occurs, in the process that completes the run, after all outcomes settle.
16. The envelope stays at version `1.0`; new event types are only the foundation-declared checkpoint/restore/cancel members.
17. Events and state documents carry safe identifiers only; raw payloads never persist.
18. Bounded-executor rules (limit 1/2, once-only, slot ownership) hold in every phase.
19. Same-case TypeScript/Python parity holds across multi-phase flows, including normalized state documents.
20. All six canonical cases run offline; M0–M3 remain valid; all evidence is bound to the current candidate revision.

M4 is complete only when executable evidence proves all these requirements for the candidate revision.

## 17. Explicit exclusions

M4 does not introduce real databases or storage engines, network or distributed state, multi-run coordination or locking, timeouts or forced termination, automatic re-execution of failed steps, real model providers, retries with side effects, approval or idempotency workflows, `UNKNOWN` outcomes (no external side effect exists to be uncertain about), Go, MCP, framework mappings, or a shared runtime extraction. These remain separate later decisions; M5 owns side effects, idempotency, and approval semantics.

## 18. Written-design review gate

The owner approved this written design and D-015 on 2026-11-01, covering the order-brief-recovery scenario reuse, the run-state document contract, checkpoint/resume/retry/cancel/replay semantics, the six canonical cases, fail-closed state loading, trace/parity boundaries, and the revision-bound authority.

The implementation plan is the next review artifact. Review that plan and select its execution method before product implementation. Design acceptance alone does not authorize product code, schema, fixture, dependency, or workflow implementation.
