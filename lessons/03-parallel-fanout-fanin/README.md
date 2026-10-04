# Lesson 03 — Bounded Fan-Out and Fan-In

Three independent reads can overlap. Their completion order must not choose the report's facts or hide missing evidence. This lesson starts from a known order ID and produces an internal structured brief. It uses no model, API key, external service, or external business write.

## Problem and Sequential Baseline

For `ORD-1001`, read order details, payment status, and delivery status. Each worker receives only its own immutable copy of `{order_id}`. No worker receives a sibling outcome, shared brief, or event sink. Sequential mode invokes the fixed queue one worker at a time with a limit of one. Use it when the reads are cheap, overlap has no useful benefit, or simpler execution is preferable. Dependent reads belong in a sequential flow rather than this independent fan-out topology.

## Justified Overlap and the Naive Failure

Parallel mode overlaps independent reads with two slots. The teaching example in `typescript/test/naive-example.test.ts` and `python/tests/test_naive_example.py` deliberately launches all three and appends to a shared brief as reads finish:

```text
launch order, payment, delivery without a bound
each worker appends its result to shared sections
release payment → delivery → order
observe three active reads and sections in payment → delivery → order order
```

The regression demonstration passes by exposing those two defects. It is isolated test/teaching code, not a CLI mode or seventh certification case. There is no timing benchmark or production speedup claim.

## Controlled Failures and the Correction

The corrected executor owns a fixed queue: `order-details`, `payment-status`, `delivery-status`. Parallel mode has two slots, not three. A slot remains occupied until a returned payload has been validated and its typed outcome recorded. A declared error or malformed output becomes one explicit failed outcome and frees the slot. Each worker is called once; there is no retry.

The finite fixture provider releases only entered workers, then waits for recorded-outcome acknowledgement. Both first parallel workers enter before either is released. In the out-of-order case, payment finishes first, delivery enters its freed slot while order remains active, then delivery and order finish. Gates prove ordering without sleeps or elapsed-time thresholds.

The collector rejects missing, duplicate, unknown, or mismatched outcomes before restoring canonical order. Only then does the runner call one deterministic synthesizer. It publishes the returned brief once; workers cannot publish a shared report. Failed workers contribute no invented facts.

| Successful workers | Status | Brief | Synthesis calls |
|---|---|---|---|
| 3 | SUCCEEDED | Three sections, complete | 1 |
| 1 or 2 | PARTIAL | Successful sections and explicit missing workers | 1 |
| 0 | FAILED / ALL_WORKERS_FAILED | null | 0 |

Worker failures are `WORKER_EXECUTION_FAILED` for declared execution errors and `INVALID_WORKER_OUTPUT` for invalid returns. Invalid raw values, private fields, cyclic objects, and arbitrary exception text never enter public trace payloads. Unexpected implementation errors stop admission, release/drain already-entered finite work, flush the inspectable trace prefix, and propagate as tooling errors. This is not a runtime cancellation/deadline or recovery feature.

The canonical complete brief is:

```json
{"order_id":"ORD-1001","sections":[{"worker_id":"order-details","output":{"order_id":"ORD-1001","order_status":"SHIPPED"}},{"worker_id":"payment-status","output":{"order_id":"ORD-1001","payment_status":"PAID"}},{"worker_id":"delivery-status","output":{"order_id":"ORD-1001","delivery_status":"DELAYED"}}],"missing_workers":[],"complete":true}
```

Delivery failure returns only order/payment sections, `missing_workers:["delivery-status"]`, `complete:false`, overall `PARTIAL`, and a retained delivery failure outcome. All failure returns `brief:null`, `synthesis_invoked:false`, and `ALL_WORKERS_FAILED`.

## Setup and Six Canonical Cases

Install M0/M1/M2 as described in the [root README](../../README.md), then:

```bash
python -m pip install -e lessons/03-parallel-fanout-fanin/python
npm ci --prefix lessons/03-parallel-fanout-fanin/typescript
```

From repository root, run these TypeScript commands:

```bash
npm --silent --prefix lessons/03-parallel-fanout-fanin/typescript run run -- --mode sequential --case sequential-complete --trace .boundrelay/manual/m3-sequential.jsonl
npm --silent --prefix lessons/03-parallel-fanout-fanin/typescript run run -- --mode parallel --case parallel-complete --trace .boundrelay/manual/m3-parallel.jsonl
npm --silent --prefix lessons/03-parallel-fanout-fanin/typescript run run -- --mode parallel --case parallel-out-of-order --trace .boundrelay/manual/m3-out-of-order.jsonl
npm --silent --prefix lessons/03-parallel-fanout-fanin/typescript run run -- --mode parallel --case parallel-partial-failure --trace .boundrelay/manual/m3-partial.jsonl
npm --silent --prefix lessons/03-parallel-fanout-fanin/typescript run run -- --mode parallel --case parallel-all-failed --trace .boundrelay/manual/m3-failed.jsonl
npm --silent --prefix lessons/03-parallel-fanout-fanin/typescript run run -- --mode parallel --case parallel-invalid-output --trace .boundrelay/manual/m3-invalid.jsonl
```

For Python, replace the command prefix through `--` with `python -m boundrelay_m3`; keep the same mode/case and use a distinct trace path. On Windows use `npm.cmd` and `.venv/Scripts/python.exe` after the corresponding environment setup. Every domain result, including PARTIAL/FAILED, emits one JSON stdout line and exits 0. Missing/unknown/duplicate/positional options and case-incompatible mode exit 2; unexpected implementation failures also exit 2 without a canonical result.

## Trace and Verification Evidence

The unchanged event envelope is version 1.0. Runs emit created/started context, one start and terminal per worker step (`worker.<id>`), optional `synthesize` start/completion, then one terminal. `run.completed` may mean SUCCEEDED or PARTIAL; inspect its status. All-failed emits `run.failed`. Fatal tooling prefixes have no canonical run terminal.

```bash
python scripts/verify_m3.py
```

The authority captures a clean candidate revision, clears stale M3 output, and invokes M2 once (which owns M1/M0). It runs shared contracts, typecheck, full language tests, required independent worker-body probes, pre-import offline guards, normal/optimized verifier-safety tests, six paired CLIs and twelve strict raw traces. It checks raw identities, lifecycle, payloads, slots, peak and fan-in before semantic projection. Same-case/mode traces keep per-worker order and business fields; sequential/parallel success comparisons use a separate business projection. The global normalizer is unchanged.

The four required executor probes must have actual passed test identities; zero tests or discovery import errors cannot certify. Evidence is written to `.boundrelay/m3/verification-evidence.json` only after lower proofs match the starting revision and the final worktree is clean with unchanged HEAD. Any tracked change invalidates earlier proof. CI runs the same command on the exact candidate SHA and uploads `m3-verification-<revision>` including hidden files and raw traces.

See [invariants.yaml](invariants.yaml), [accepted design](../../docs/superpowers/specs/2026-10-05-m3-bounded-fanout-fanin-design.md), and [implementation plan](../../docs/superpowers/plans/2026-10-05-m3-bounded-fanout-fanin.md). Local/CI evidence proves this finite offline lesson, not live service consistency, model behavior, production latency or recovery. Go, MCP, dynamic topology, real providers, external writes, persistence and runtime deadlines/cancellation remain outside M3.

## Exercises

1. Run sequential-complete and parallel-out-of-order; compare raw worker lifecycles and equal business briefs.
2. Run delivery failure; identify which output is missing and why `run.completed` does not establish full success.
3. Run invalid payment output; verify UNKNOWN appears only in the fixture, not the accepted outcome or trace.
4. Remove the admission cap or merge by arrival order in a disposable experiment; run the independent probes and synthesis tests to observe the failure. Restore the implementation before certification.
