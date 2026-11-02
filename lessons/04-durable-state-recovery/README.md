# Lesson 04 — Durable State and Recovery

A crash must not erase knowledge the runtime already recorded, and a display history must never be mistaken for recoverable state. This lesson reuses the three `order-brief` workers unchanged and adds a typed run-state document, write-ahead atomic checkpoints, fail-closed resume and replay, and deterministic cancellation. It uses no model, API key, external service, storage engine, or external business write.

## History Versus State

Two artifact classes exist and must not be conflated:

- **User-facing history:** the strict JSONL event trace and the single JSON result line. Append-only, inspection-oriented, and never read back by the runtime.
- **Run state:** one engine-owned document per run under the `--state-dir`, validated against a closed schema and consulted on resume. Small, typed, digest-protected, and authoritative for recovery.

The state document lives at `<state-dir>/<run_id>/state.json` with immutable snapshots at `checkpoints/step-<seq>.json`. Every write is atomic (temporary file plus rename), and each step terminal also snapshots its document. The `digest` field is the SHA-256 of the canonical JSON body without the digest field itself.

## The Naive Failure: Retry Everything

The teaching example in `typescript/test/naive-example.test.ts` and `python/tests/test_naive_example.py` simulates an interrupted run — order recorded, payment and delivery never started — then retries naively:

```text
interrupted run: order-details recorded, process dies
naive retry:     invoke all three workers again  → order runs twice
corrected resume: skip recorded order, run payment + delivery only
```

The demonstration proves the naive retry duplicates work (four total invocations) while the corrected resume adds exactly the two missing invocations (three total). Retry is the right answer only when recorded state cannot be trusted or steps are cheaper than recovery logic — before any step has side effects.

## The Correction: Write-Ahead Checkpoints

The executor records every step terminal through the store **before** the next admission, so a crash can lose at most the step that was in flight, never a recorded terminal. Admission marks a worker `RUNNING` in the document before its body starts. `sequence_cursor` counts recorded terminals; resume derives its pending set from the step statuses, in canonical queue order.

Loading state fails closed. A truncated file, unknown schema version, invalid document, digest mismatch, or binding mismatch is a tooling error — exit `2`, no result line, and **zero worker invocations**. Corruption is evidence, never a prompt to silently restart.

## Resume, Replay, and Cancellation

| Situation | Status | Result line | Exit |
|---|---|---|---|
| Clean completion | `SUCCEEDED` / `PARTIAL` | yes | `0` |
| All workers failed | `FAILED` / `ALL_WORKERS_FAILED` | yes | `0` |
| Scripted cancellation | `CANCELLED` | yes | `0` |
| Crash control | tooling failure | no | `2` |
| Corrupt/invalid state load | tooling failure | no | `2` |

Resume never re-invokes a recorded `SUCCEEDED` or `FAILED` outcome; only a worker without a recorded terminal runs again, exactly once. A fully recorded run resumes with zero admissions and completes by synthesis alone. `CANCELLED` is a domain outcome with no failure code, and a cancelled run resumes into only its remaining workers. Replay (`--replay-from <snapshot>`) seeds a **new** run identity from a validated snapshot and never mutates the source files.

## Canonical Cases

Six paired offline cases, all in parallel mode:

| Case | Phases | Outcome |
|---|---|---|
| `parallel-clean-complete` | 1 run | `SUCCEEDED`, checkpoint after every step |
| `parallel-crash-resume` | crash + resume | phase 1 exits `2` with durable state; resume `SUCCEEDED`; order/payment invoked exactly once across processes |
| `parallel-crash-resume-partial` | crash + resume | resume `PARTIAL`; the recorded failure is not re-executed |
| `parallel-cancel-resume` | cancel + resume | phase 1 `CANCELLED` (exit `0`); resume `SUCCEEDED` |
| `parallel-replay-from-checkpoint` | run + replay | same brief as the source run; source bytes untouched |
| `parallel-corrupt-state` | run + tampered resume | exit `2`, no result line, zero invocations |

Example flow for the crash-resume case:

```bash
python -m boundrelay_m4 --case parallel-crash-resume --trace crash1.jsonl --state-dir state   # exit 2, durable state
python -m boundrelay_m4 --case parallel-crash-resume --trace crash2.jsonl --state-dir state --resume   # exit 0, SUCCEEDED
npx tsx src/cli.ts --case parallel-crash-resume --trace crash1.jsonl --state-dir state
npx tsx src/cli.ts --case parallel-crash-resume --trace crash2.jsonl --state-dir state --resume
```

Each completed phase emits exactly one nonblank JSON result line. Crash and corruption phases emit none. Traces gain `checkpoint.saved`, `checkpoint.restored`, and `run.cancelled` from the foundation's declared event family; a crash phase ends without any terminal event — the durable state document is its only testimony.

## Invariants and Verification

The twenty invariants (`M4-01`–`M4-20` in `invariants.yaml`) cover the history/state boundary, write-ahead ordering, fail-closed loading, exactly-once recorded outcomes, retry contrast, cancellation and replay semantics, one synthesis call in the completing process, event privacy, bounded-executor rules in every phase, multi-phase language parity, and revision-bound evidence.

The authority is `python scripts/verify_m4.py`: it chains the M3 (and therefore M2→M1→M0) authorities on the same clean revision, runs both language suites, mutation-tested raw validation, and all six multi-phase case flows with real subprocess exits. Evidence is published under `.boundrelay/m4/verification-evidence.json` only for an unchanged HEAD. CI uploads `m4-verification-<revision>`.

## Limits

No real storage engine, network state, locking, timeouts, forced termination, automatic re-execution of failures, `UNKNOWN` outcomes, approval/idempotency, real providers, Go, MCP, or framework mappings. Those belong to later milestones; M5 owns side effects.

