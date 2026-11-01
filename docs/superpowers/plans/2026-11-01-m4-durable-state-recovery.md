# M4 Durable State and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The owner selected Native execution on 2026-11-01.

**Goal:** Deliver the accepted offline `order-brief-recovery` lesson with a typed run-state document, write-ahead atomic checkpoints, fail-closed resume/replay, deterministic cancellation, and exact-revision evidence across a multi-process authority chain.

**Architecture:** Keep each language implementation lesson-local. A validated state store owns the run-state document and immutable per-step checkpoint snapshots; a bounded executor (M3 rules) admits workers under crash/cancel controls; resume/replay loaders restore validated state before admission; the completing process performs exactly one synthesis after complete fan-in. Raw trace/state checks precede semantic projections. One M4 authority owns the M3→M2→M1→M0 regression chain and multi-phase subprocess evidence.

**Tech Stack:** Node.js >=24, Python >=3.14, TypeScript strict ESM, Vitest, tsx, Ajv/ajv-formats, PyYAML, jsonschema, unittest, Node `crypto` / Python `hashlib` for SHA-256 digests. Reuse M3's manifest/configuration patterns and pinned versions (vitest 4.1.12, ajv 8.20.0); no new dependency.

**Spec:** [Accepted M4 design](../specs/2026-11-01-m4-durable-state-recovery-design.md), [D-015](../../decisions/D-015-m4-durable-state-and-recovery.md), accepted 2026-11-01.

**Status:** Written design and implementation plan accepted on 2026-11-01. The owner selected Native execution; implementation proceeds on the feature branch. Exact-revision certification, independent review, CI, merge, and release remain separate observed states; consult PR evidence for their current status.

## Global Constraints

- Scenario `order-brief-recovery`; canonical input `ORD-1001`; the three M3 workers, their closed output schemas, enums, and failure codes are reused unchanged.
- The run-state document is the **only recovery authority**. Traces and results are append-only user-facing history and are never read back for recovery decisions.
- State layout: `<state-dir>/<run_id>/state.json` plus immutable snapshots `checkpoints/step-<seq>.json`. Every step terminal is checkpointed before the next admission (write-ahead). Admission marks the worker `RUNNING` in the state document before body entry, so resume distinguishes in-flight (`RUNNING` without terminal) from never-started (`PENDING`); both re-execute exactly once.
- State document fields: `state_schema_version: "1.0"`, `run_id`, `scenario_id`, `case_id`, `execution_mode`, `concurrency_limit`, `requested_order_id`, `status` (`RUNNING|SUCCEEDED|FAILED|CANCELLED`), `steps` (per fixed worker: `worker_id`, `status` `PENDING|RUNNING|SUCCEEDED|FAILED|CANCELLED`, validated typed `outcome` or fixed `failure_code`, never a raw rejected payload), `sequence_cursor`, `digest` = SHA-256 hex over the canonical JSON body without the digest field.
- State writes are atomic: temporary file in the same directory, then rename. A truncated or partially written file is never loaded; discovering one is a tooling failure. Snapshots are immutable once renamed.
- Loading state fails closed: unknown/missing `state_schema_version`, schema-invalid document, digest mismatch, binding mismatch (case/mode/order), truncated/partial file, or missing/invalid snapshot is a tooling error — CLI exit `2`, no result line, **zero worker invocations**.
- Resume: load and validate state, emit `checkpoint.restored`, re-admit only workers without a recorded terminal in canonical queue order under M3's bounded-executor rules (limit 2 parallel here), never re-invoke recorded `SUCCEEDED`/`FAILED` outcomes, exactly one synthesis call in the completing process after all outcomes settle. Request/state binding mismatch is a tooling error.
- Retry is a fresh run with a fresh identity consulting no durable state; it re-executes every worker. It stays a walkthrough/unit-level contrast, not a canonical case.
- Cancellation (`cancel_before`): stop new admissions before the named worker, drain entered workers, record and checkpoint their terminals, mark later workers `CANCELLED` step status, write final state with `status: CANCELLED`, emit `run.cancelled`, return a domain result — one JSON line, exit `0`, no failure code. A cancelled run is resumable.
- Replay (`--replay-from <checkpoint>`): load a validated snapshot into a **new** run identity; the source run's files stay byte-identical. Replay completes like a resume.
- Result wire: M3's result shape plus `status` gaining `CANCELLED`, `resumed`, `restored_cursor`, `restored_worker_ids`, `state_dir`, `run_state_status`. Worker outcomes, synthesis flag, brief, and failure-code semantics stay exactly M3's.
- Envelope stays `1.0`; the event-type enum gains exactly the foundation-declared `checkpoint.saved`, `checkpoint.restored`, `run.cancelled`. Payloads carry binding fields, `step_name`, `state_status`, `sequence_cursor`, counts, and `cancelled_before` + fixed code `CANCELLED_BEFORE_STEP` — safe identifiers only. A crash phase ends with **no terminal event**; the durable state document is its only testimony. Resumed phases keep one `run_id` with fresh per-process sequences.
- Exactly six canonical cases (all parallel mode), with real two-phase subprocess flows for crash/cancel cases; exactly one nonblank JSON result line per completed phase; crash and corrupt phases emit no result line and exit `2`. Extra adversarial tests and the naive teaching example are not new CLI modes/cases.
- Stay offline and framework-free. Exclude real storage engines, network/distributed state, multi-run coordination/locking, timeouts/forced termination, automatic failure re-execution, `UNKNOWN` outcomes, real providers, Go, MCP, framework mappings, and shared-runtime extraction (M5+ boundaries).
- Publish evidence only on a clean unchanged candidate revision, after M3 (and its lower chain) pass on that same revision. Safety checks must survive `python -O`.

## Review Focus

| Failure/input class | Required evidence | Owner |
|---|---|---|
| Gate loads tampered/stale/binding-mismatched state and proceeds | Digest/version/binding fail-closed tests; zero invocations; exit 2 | Tasks 2, 4 |
| Resume re-executes a recorded worker or loses a recorded outcome | Cross-process exactly-once probes with independently instrumented worker bodies | Tasks 3–4 |
| Crash phase flushes a result line/terminal despite abort, or resume invents outcomes | Subprocess exit-2 + empty-stdout assertions; merged outcome records; state doc is testimony | Tasks 5–6 |
| Replay mutates its source state | Byte-identical source snapshot before/after assertion | Tasks 4, 6 |
| Parity projection hides checkpoint/restore/cancel behavior or state drift | Raw-first mutation tests including checkpoint ordering, restore-before-start, normalized state comparison | Task 6 |
| Certification without real subprocess durability proof | Multi-phase case records with per-phase exit codes and artifact digests | Tasks 6–7 |

## File and Interface Map

Use `TS = lessons/04-durable-state-recovery/typescript` and `PY = lessons/04-durable-state-recovery/python`. All paths below are repository-relative; braces enumerate exact files. Python module prefix is `boundrelay_m4`.

| Files | Responsibility |
|---|---|
| `contracts/state/order-brief-run-state.schema.json`, `contracts/results/order-brief-recovery-result.schema.json` | Closed run-state document and result schemas |
| `fixtures/scenarios/order-brief-recovery.yaml` (reusing `fixtures/workers/order-brief/*`) | Six cases, crash/cancel/tamper controls, completion schedules |
| `TS/src/{types,paths,schemas,scenario,workers,scripted-workers,state-store}.ts`; `PY/src/boundrelay_m4/{types,paths,schemas,scenario,workers,scripted_workers,state_store}.py` | Types, state validation, digest, atomic store, controls |
| `TS/src/executor.ts`; `PY/src/boundrelay_m4/executor.py` | Bounded admission with crash/cancel controls, validated outcomes |
| `TS/src/{collector,synthesizer}.ts`; Python equivalents | Complete fan-in, canonical order, brief construction (M3 contracts) |
| `TS/src/{recovery,trace,runner,cli}.ts`; Python equivalents and `__main__.py` | Resume/replay loaders, event lifecycle, orchestration, CLI contract |
| `tools/parity/{verify_m4,test_m4_verification_safety}.py`, `scripts/verify_m4.py` | Raw checks, multi-phase parity, gate, proof publication |
| `lessons/04-durable-state-recovery/{README.md,invariants.yaml}`, `.github/workflows/m4.yml` | Teaching, invariant map, exact-head CI |

### Stable Interfaces

Define these in Task 2; subsequent tasks consume the same names and wire fields. Python uses snake_case for internal APIs and the identical snake_case JSON wire fields.

- `RunStateDocument`, `RunStateStatus`, `StepRecord`, `StateBinding` (case/mode/order/limit). `validateRunStateDocument(raw): ValidationResult<RunStateDocument>` / `validate_run_state_document(...)`; `canonicalStateBody(document): string` / `canonical_state_body(...)`; `stateDigest(body): string` / `state_digest(...)` — SHA-256 hex over the canonical JSON body without `digest`.
- `StateStore`: `create(binding, queue)`, `markRunning(worker)`, `recordStepTerminal(worker, outcome)`, `markCancelledFrom(worker)`, `markTerminal(status, failureCode?)`, `state()`, `statePath()`, `snapshotPath(seq)`; Python snake_case equivalents. All writes atomic (temp + rename); each terminal write also snapshots `step-<seq>.json`; digest recomputed per write.
- `loadRunState(stateDir, expectedBinding)` / `load_run_state(...)` returns `{document, restored_from}` or raises typed `StateLoadError` with a fixed reason (`UNKNOWN_VERSION | SCHEMA_INVALID | DIGEST_MISMATCH | BINDING_MISMATCH | TRUNCATED | MISSING_SNAPSHOT`) — never raw payloads in the error.
- `RecoveryControls`: `{crashAfter?: WorkerId, cancelBefore?: WorkerId}`; a case defines at most one; `tampered_state` lives in scenario metadata applied by the parity harness, never by the runtime.
- `ExecutorOptions` extends M3's shape with `controls: RecoveryControls`; `ExecutionSummary` unchanged (completion-ordered outcomes + peak concurrency). `executeWorkers(options)` / `execute_workers(options)` — limit by mode, once-only, declared failures release slots, fatal unexpected errors drain entered work exactly as M3.
- `canonicalizeOutcomes` / `synthesizeBrief` re-declared lesson-locally with M3's exact contracts.
- `RunOptions`: `{caseId, tracePath, stateDir, resume?, replayFrom?, directory?, control?, synthesizer?, stateStore?}`; override pairs supplied together. `runCase(options)` / `run_case(...)`. The crash control hard-exits with code 2 after durable flush (`process.exit(2)` / `os._exit(2)`) — no result, no terminal.
- `TraceSink.emit(type, data) / flush()` as M3; the lesson-local event context gains the three new event types with the payload rules above; sequences/ids stay per-process; a resumed phase continues the same `run_id`.
- `CaseSpec` holds case ID, mode, worker fixture path, completion order, optional controls; `loadScenario()` returns the validated six-case scenario with feasible schedules.

### Canonical Cases

All parallel (limit 2), canonical queue order, payment, delivery; controlled completion order; at most one active control per case; crash/cancel targets settle last in their phase so boundaries are timing-independent; resume phases rerun the full CLI.

| Case | Phases | Injected difference | Result |
|---|---|---|---|
| `parallel-clean-complete` | 1 run | none | `SUCCEEDED` / peak 2; checkpoint after every step |
| `parallel-crash-resume` | 2 runs | `crash_after: payment-status` | Phase 1 exit 2, no result line; phase 2 `SUCCEEDED`; order/payment invoked exactly once across processes |
| `parallel-crash-resume-partial` | 2 runs | `crash_after: delivery-status` + declared delivery failure | Phase 1 exit 2; phase 2 `PARTIAL`, delivery missing; recorded failure never re-executed |
| `parallel-cancel-resume` | 2 runs | `cancel_before: delivery-status` | Phase 1 `CANCELLED` (result line, exit 0); phase 2 `SUCCEEDED` complete |
| `parallel-replay-from-checkpoint` | replay from `step-1` snapshot | new run seeded with order outcome | `SUCCEEDED`, identical brief; source state byte-identical |
| `parallel-corrupt-state` | resume with tampered state | tampered `steps.payment-status` outcome + stale digest | Tooling error, exit 2, zero invocations, no result line |

Here order/payment/delivery abbreviate the full worker IDs, never fixture wire values.

## Commands and Working Directory

Use repository root as explicit cwd. On this Windows host use `.venv/Scripts/python.exe` for `python`, and `npm.cmd` for `npm`; CI uses its configured executables. Resolve subprocess executables through `shutil.which`, preserving the established Windows npm fix. Set `$env:PYTHONPATH='lessons/04-durable-state-recovery/python/src'` before Python unit commands. Commands below use `python`/`npm` as portable notation.

- TS unit/type checks: `npm --prefix lessons/04-durable-state-recovery/typescript test -- test/<file>.test.ts`; `npm --prefix lessons/04-durable-state-recovery/typescript run typecheck`.
- Python unit checks: `python -m unittest discover -s lessons/04-durable-state-recovery/python/tests -p test_<file>.py -v`.
- A RED step must fail on its named behavioral assertion or missing implementation, not missing packages or bad cwd. Establish dependencies first. After each task's GREEN steps, run its affected tests and TS typecheck, inspect the diff, stage only its files, and commit with the specified message. Run the complete clean-revision authority after Task 7; intermediate task checks do not certify M4.

## Task 1: Shared Contracts, Fixtures, and Invariant Catalog

**Files — Create:** `contracts/state/order-brief-run-state.schema.json`, `contracts/results/order-brief-recovery-result.schema.json`, `fixtures/scenarios/order-brief-recovery.yaml`, `tools/contracts/test_m4_contracts.py`, `lessons/04-durable-state-recovery/invariants.yaml`.

**Interfaces:** Produce JSON Schema conventions matching M3, the closed run-state schema (fields/digest exclusion per Global Constraints), the result schema extending M3's with `CANCELLED` + recovery fields, and YAML scenario `{schema_version:'1.0',scenario_id,order_id,cases}`. Each case adds optional `controls: {crash_after?, cancel_before?}` (at most one) or a `tampered_state` marker. Worker fixtures are reused from `fixtures/workers/order-brief/`. No new worker grammar.

- [ ] Write `test_six_cases_and_closed_state_contract` and `test_result_status_count_policy` with these assertions:
  ```python
  self.assertEqual(len(scenario['cases']), 6)
  self.assertEqual(len({c['case_id'] for c in scenario['cases']}), 6)
  self.assertFalse(state_schema_accepts({**valid_state, 'extra_key': 1}))
  self.assertFalse(state_schema_accepts(valid_state_with_digest_over_wrong_body))
  self.assertFalse(result_accepts(cancelled_with_failure_code))
  self.assertFalse(result_accepts({**partial_result, 'complete_in_brief': True} | {'resumed': True, 'restored_cursor': None}))
  ```
  Define helpers inside the test module using Draft202012Validator and the real schema files. Add negative candidates: wrong binding fields, missing digest, digest computed over the wrong body, missing/extra step records, unknown status enums, extra result keys, `CANCELLED` + failure_code, `resumed: true` with missing recovery fields.
- [ ] Run `python -m unittest tools.contracts.test_m4_contracts -v`; expect RED on missing contracts/fixtures or candidate acceptance.
- [ ] Implement closed schemas, exact six cases with at-most-one control each and feasible schedules, reused worker fixtures, and a twenty-entry invariant catalog keyed `M4-01` through `M4-20` mapped to spec section 16.
- [ ] Rerun the contract command; expect all tests PASS, including deliberately invalid fixture behavior.
- [ ] Commit only Task 1 files: `feat: define M4 run-state contracts and recovery fixtures`.

## Task 2: Language Foundations: State Store, Digest, and Controlled Scenario

**Files — Create:** `TS/{package.json,package-lock.json,tsconfig.json,.nvmrc}`; `TS/src/{types,paths,schemas,scenario,workers,scripted-workers,state-store}.ts`; `TS/test/{foundations,state-store,scenario,schemas,scripted-workers}.test.ts`; `PY/{pyproject.toml,requirements-dev.txt}`, `PY/src/boundrelay_m4/__init__.py` and matching Python sources; `PY/tests/test_{foundations,state_store,scenario,schemas,scripted_workers}.py`.

**Interfaces:** Produce the Stable Interfaces for types/validation/digest/store/scenario/scripted workers (not executor/recovery/runner). `loadScenario` validates fixed topology, unique six case IDs, at-most-one control per case, feasible schedules, and reused worker fixture paths. `StateStore` performs atomic writes and immutable snapshots; the JSON Schema of the document is enforced with Ajv/jsonschema before any write is published.

- [ ] Scaffold M4 manifests from M3 with names `@boundrelay/lesson-04-typescript` and `boundrelay-m4`, no new dependencies; pinned versions from main (vitest 4.1.12). Install with `npm --prefix lessons/04-durable-state-recovery/typescript install` and `python -m pip install -r lessons/04-durable-state-recovery/python/requirements-dev.txt`. Commit the generated lockfile; follow existing strict TS settings.
- [ ] Write paired state-store tests. `reject_tampered_state_document`: flip one outcome value, expect `DIGEST_MISMATCH`; bump `state_schema_version`, expect `UNKNOWN_VERSION`; remove `sequence_cursor`, expect `SCHEMA_INVALID`; bind to a different case, expect `BINDING_MISMATCH`; truncate the JSON mid-file, expect `TRUNCATED`; all failures carry the fixed reason and no raw payload. `atomic_write_leaves_previous_state_loadable`: inject an interrupted write (partial temp file, no rename) and assert the previous document still loads and the temp file is discarded.
- [ ] Write paired scenario tests: at-most-one-control rejection, infeasible crash/cancel targets (target must settle last in its phase), unknown control fields, reused-fixture path validation.
- [ ] Run the affected TS/Python test files; expect RED on missing store/digest/control behavior.
- [ ] Implement signatures and fixed grammar. Canonical JSON body = sorted keys, no whitespace, UTF-8; digest over body without `digest`. Store validates every candidate document against the closed schema before publish; never repair invalid documents.
- [ ] Run all Task 2 tests plus typecheck; expect PASS with atomic durable writes and successful imports from repository root.
- [ ] Commit only Task 2 files: `feat: add M4 typed state store and recovery foundations`.

## Task 3: Bounded Executor with Crash and Cancel Controls

**Files — Create:** `TS/src/executor.ts`, `TS/test/executor.test.ts`, `PY/src/boundrelay_m4/executor.py`, `PY/tests/test_executor.py`.

**Interfaces:** Consume Task 2 store/directory/control types; produce M3's `executeWorkers` contract extended with `controls`. The executor marks `RUNNING` in the store at admission, records validated terminals through the store before observer notification, honors `cancel_before` (stop admission before the named worker, drain entered work, return completion-ordered outcomes plus a `cancelledBefore` marker), and honors `crash_after` only after the named terminal is durably recorded **and no worker is in flight** in that phase.

- [ ] Write paired `parallel_calls_overlap_without_exceeding_two` and `sequential_never_overlaps` with independently instrumented worker bodies (M3 probe names must survive): body max active equals 2/1, each worker invoked once, isolated copied inputs.
- [ ] Write paired `cancel_before_stops_admission_and_records_drained_terminals`: cancel before delivery; order/payment settle and are recorded + checkpointed; delivery step status `CANCELLED`; returned summary marks the boundary; no synthesis has run.
- [ ] Write paired `crash_after_requires_quiescent_boundary`: crash control fires only when the named worker's terminal is recorded and the active set is empty; assert store state is `SUCCEEDED`-for-recorded-steps with `status: RUNNING` and cursor unchanged before the hard exit.
- [ ] Run executor tests in both languages; expect RED on missing control handling.
- [ ] Implement `executeWorkers` with the store-integrated admission loop, once-only invocation, declared failures releasing slots, fatal unexpected errors draining entered work exactly as M3 (tooling path, no canonical result).
- [ ] Run complete executor tests plus typecheck; expect PASS. Preserve the exact probe test names (Python `ExecutorTests.test_<name>`); Task 6 requires their passed identities.
- [ ] Commit only Task 3 files: `feat: bound M4 worker admission with crash and cancel controls`.

## Task 4: Resume, Replay, and Cancel-Resume Lifecycle

**Files — Create:** `TS/src/recovery.ts`, `TS/test/recovery.test.ts`, `PY/src/boundrelay_m4/recovery.py`, `PY/tests/test_recovery.py`.

**Interfaces:** Consume `loadRunState`, `StateStore`, executor, collector, synthesizer. Produce `resumeRun(options)` / `resume_run(options)`: load → validate → emit `checkpoint.restored` → seed recorded outcomes → admit only unrecorded workers → complete fan-in and exactly one synthesis in this process. `replayFrom(snapshotPath, options)` / `replay_from(...)`: load validated snapshot into a **new** run identity and behave like resume; source files untouched.

- [ ] Write paired `resume_skips_recorded_workers_and_reexecutes_inflight_exactly_once`: seed a state with order `SUCCEEDED`, payment `RUNNING` (in-flight), delivery `PENDING`; run resume with instrumented bodies; order invocation count 0, payment 1, delivery 1; merged outcomes complete; synthesis called once.
- [ ] Write paired `resume_never_reexecutes_recorded_failures`: seed delivery `FAILED`/`WORKER_EXECUTION_FAILED`; resume yields `PARTIAL` with delivery missing and invocation count 0 for delivery; recorded outcome flows to synthesis unchanged.
- [ ] Write paired `replay_seeds_new_run_without_touching_source`: capture source snapshot bytes; replay from `step-1`; new `run_id`, order skipped, payment/delivery run; brief identical to the seeded full run; source bytes unchanged.
- [ ] Write paired `cancel_resume_completes_remaining_workers_only`: seed `CANCELLED` state with delivery `CANCELLED`; resume yields `SUCCEEDED` complete; delivery invoked once; `restored_worker_ids` lists order/payment.
- [ ] Write paired binding-mismatch tests: requested case/mode/order differing from the document raises `StateLoadError` with `BINDING_MISMATCH` and invokes zero workers.
- [ ] Run recovery tests in both languages; expect RED on missing loaders/admission behavior.
- [ ] Implement `resumeRun`/`replayFrom` with fail-closed loading, canonical-queue cursor admission, exactly-once re-execution, and one synthesis in the completing process; emit `checkpoint.restored` before any worker start.
- [ ] Run all Task 4 tests plus typecheck; expect PASS.
- [ ] Commit only Task 4 files: `feat: implement M4 resume and replay from validated checkpoints`.

## Task 5: Runner, Multi-Phase CLI, Trace Events, and Offline Guards

**Files — Create:** `TS/src/{trace,runner,cli}.ts`, `TS/test/{runner,cli,offline,multiphase}.test.ts`, `TS/test/helpers/offline-runner.ts`; `PY/src/boundrelay_m4/{trace,runner,cli,__main__}.py`, `PY/tests/test_{runner,cli_trace,offline}.py`, `PY/tests/offline_runner.py`.

**Interfaces:** Consume executor/recovery/store; produce `TraceSink` and `runCase` extended with `stateDir/resume/replayFrom`. CLI options exactly `--case <id> --trace <path> --state-dir <dir> [--resume] [--replay-from <path>]`; mode comes from the case. Reject unknown/duplicate/positional/missing arguments before any state load or worker call. Domain results (`SUCCEEDED|PARTIAL|FAILED|CANCELLED`) emit one JSON line, exit `0`; crash/corrupt phases exit `2` with no result line.

- [ ] Write paired `checkpoint_events_precede_next_admission_and_restore_precedes_starts`: with gated bodies, `checkpoint.saved` for a step terminal precedes the next worker's start; in a resuming process, `checkpoint.restored` precedes every worker start; payloads carry only binding fields, `step_name`, `state_status`, `sequence_cursor`, counts.
- [ ] Write paired `cancelled_run_is_domain_outcome`: `run.cancelled` carries `cancelled_before` + `CANCELLED_BEFORE_STEP`; result line has `status: CANCELLED`, `failure_code: null`, exit 0; later workers marked `CANCELLED` step status; state document final status `CANCELLED`.
- [ ] Write paired `crash_phase_exits_without_result_or_terminal`: run the CLI in a subprocess with `crash_after`; assert exit 2, empty stdout, trace ends after the last `checkpoint.saved`, no run terminal event; the state document is loadable by the next phase.
- [ ] Write paired runner lifecycle tests: `run.created/started` bind case/mode/order/limit and the state path; worker/synthesis/terminal events follow M3 payload rules; `resumed: true` results carry `restored_cursor`, `restored_worker_ids`, `state_dir`, `run_state_status`; exactly one terminal per completed phase.
- [ ] Write paired strict-CLI tests: unknown/duplicate/positional/missing arguments and `--replay-from` combined with `--resume` rejected before any load; missing `--state-dir` is a tooling error.
- [ ] Run runner/CLI tests in both languages; expect RED on absent lifecycle/CLI behavior.
- [ ] Implement runner lifecycle with store integration: emit `checkpoint.saved` after each recorded terminal, `checkpoint.restored` after a validated load, synthesis/terminal as M3; flush trace prefix on the fatal path without appending a terminal.
- [ ] Implement strict CLI parsing and the multi-phase contract above. Python module CLI `python -m boundrelay_m4`; TS run script `tsx src/cli.ts`.
- [ ] Write offline launch tests following M2/M3's pre-import guard pattern; prove a deliberately network-using import is blocked in a fresh process; no API keys required.
- [ ] Run Task 5 tests plus typecheck; expect PASS for lifecycle counts, event ordering, domain/tooling exit separation, and blocked network probes.
- [ ] Commit only Task 5 files: `feat: expose M4 multi-phase runs and validated trace lifecycle`.

## Task 6: Raw-First Parity and Exact-Revision Verification Authority

**Files — Create:** `tools/parity/{verify_m4,test_m4_verification_safety}.py`, `scripts/verify_m4.py`. **Reuse without changing semantics:** `tools/parity/normalize.py`, lower milestone authorities, shared event schema, and M3's probe-report validation patterns.

**Interfaces:** `assert_case_behavior(result, events, case, trace_path, source, phases) -> None` checks raw lifecycle/result/state bindings across all phases; `semantic_trace(...)` calls the raw assertion before projection; `normalize_state(document) -> dict` strips `run_id`, paths, timestamps, and runtime metadata while validating digest integrity within each document; `business_projection(result)` uses an explicit allowlist; `publish_evidence(evidence, starting_revision)` rejects dirty/moved HEAD and mismatched lower proof; `validate_probe_reports(ts_report, python_report)` demands the required passed executor probe identities and nonzero suites.

- [ ] Write `test_raw_mutations_fail_before_projection`: mutate missing/duplicate `checkpoint.saved`, restore after a worker start, re-executed recorded worker across phases, lost phase-1 outcome, `CANCELLED` result with failure code or exit mismatch, crash phase with a result line or terminal, replay mutating source state, tampered state loading, wrong binding, noncontiguous sequence, duplicate event ID, NaN/blank JSONL, early synthesis, false peak/limit, mismatched brief, duplicate terminal. Assert each raises before normalization.
- [ ] Run `python -m unittest tools.parity.test_m4_verification_safety -v`; expect RED on missing verifier or acceptance of mutations.
- [ ] Implement raw checks: per-phase strict JSONL/envelope validation, one terminal per completed phase, no terminal in crash phases, checkpoint ordering, restore-before-starts, merged outcome identity (exactly one recorded outcome per worker across phases), and state-document schema/digest/binding validation.
- [ ] Implement same-case language comparison: normalized results, per-worker lifecycles projected across the phase boundary, checkpoint/restore/cancel event behavior, and normalized state documents. Business projection compares clean vs crash-resumed vs cancel-resumed vs replayed runs reaching the same outcomes (order ID, final status, worker outcomes, synthesis flag, brief).
- [ ] Write `test_missing_probe_or_zero_suite_cannot_certify` and `test_publication_checks_survive_optimization` (stale evidence cleared first; failed chain, wrong lower SHA/status, moved HEAD, dirty tree cannot publish; suite also passes under `python -O`).
- [ ] Implement the top gate: capture clean starting SHA; clear only `.boundrelay/m4`; invoke M3 once; validate lower evidence SHA/status; run shared contracts, TS typecheck/full tests with the Vitest JSON reporter, full Python tests with a collecting unittest result, verifier safety, offline guards, six multi-phase case flows with per-phase exit/stdout assertions, raw trace + normalized state comparisons, and business equality; recheck clean HEAD and publish.
- [ ] Record command/runtime versions, revision, per-phase exit codes, six case records, all phase trace paths, normalized state comparisons, full test counts, and required passed probe identities. Never use `--passWithNoTests`.
- [ ] Run normal and optimized verifier-safety tests plus both language suites/typecheck; expect PASS. Full authority remains deferred until Task 7's complete committed candidate.
- [ ] Commit only Task 6 files: `test: certify M4 multi-phase parity and durability evidence`.

## Task 7: Teaching Demonstration, CI, and Candidate Certification

**Files — Create:** `lessons/04-durable-state-recovery/README.md`, `.github/workflows/m4.yml`, `TS/test/naive-example.test.ts`, `PY/tests/test_naive_example.py`. **Modify:** root `README.md`, `.ai/delivery/current-scope.md`, the M4 invariant catalog and this plan's completion checkboxes only when actually earned.

**Interfaces:** A test-local naive example is pedagogical, never imported by the CLI. CI runs `python scripts/verify_m4.py` on the exact candidate SHA with Node 24 / Python 3.14, uploads `m4-verification-<revision>` including hidden files. M3 remains the implemented authority until the new authority actually passes.

- [ ] Write paired `retry_without_state_duplicates_every_invocation`: after an interrupted run, the naive retry re-executes all three workers (proof of duplicated work), while the corrected resume re-executes only the unrecorded worker. The regression demonstrates both behaviors with instrumented bodies; no sleep, benchmark, external call, or seventh case.
- [ ] Run naive example tests; expect RED before the demonstration exists; implement it only inside test modules and rerun; expect PASS.
- [ ] Write the lesson README: the history-versus-state boundary → baseline without durability → naive retry failure → typed state document → write-ahead checkpoints → fail-closed loading → resume/replay/cancel semantics → evidence. Include exact multi-phase CLI commands, state-document and digest examples, exit-code table, crash/cancel/corruption rationale, invariants, and evidence limits. Explain when full retry is the better choice; make no durability claim beyond what the evidence shows.
- [ ] Add the exact-head M4 workflow using current repository action versions, `persist-credentials: false`, existing PR/main triggers, lower-chain dependencies, and hidden evidence upload. Never certify an uncommitted or synthetic merge tree as the PR head. Update root README and scope to point to the M4 authority only with precise implementation status.
- [ ] Inspect scope/diff, run `git diff --check`, then commit Task 7 files: `docs: teach M4 recovery and enable revision bound CI`. Do not change M0–M3 domain code or the global normalizer.
- [ ] On the clean committed candidate run `python scripts/verify_m4.py`; expect PASSED evidence on the exact starting/current SHA, lower chain PASSED, M4 six case records with per-phase exit codes, all phase traces validated, and all required independent probes passed. If any fix changes tracked files, commit it and rerun the authority on the new clean revision.
- [ ] Run one fresh whole-branch independent review using the chosen execution workflow, resolve material findings within accepted scope, and rerun only affected checks plus a fresh full authority when a change invalidates evidence. Preserve fail-closed loading, write-ahead ordering, and raw-first proof as review priorities.
- [ ] Push the branch/update its draft PR description around final implemented behavior and validation. Check M0–M4 CI on the exact latest head and verify the downloaded M4 artifact SHA/status/case counts. Mark ready only after required checks and review pass; merge/release require the owner's separate authorization.
- [ ] Append one completed-task activity entry and update project continuation state with the actual SHA, PR/CI/evidence status, remaining blockers, and the next bounded action. Never label unobserved CI or M4 production behavior as proved.

## Inline Self-Review and Coverage

Reviewed this plan against all spec sections and twenty invariants. Tasks 1–2 fix state contracts, digest, atomic store, and control grammar; Task 3 owns bounded admission with crash/cancel; Task 4 owns fail-closed resume/replay and exactly-once semantics; Task 5 owns multi-phase publication, trace events, CLI, and offline guards; Task 6 owns raw validation, state comparison, probe proof, and evidence; Task 7 owns the D-005 teaching sequence, CI, and completion. No M4 product code is included in this planning change.

| Spec invariants | Implementation and evidence |
|---|---|
| 1–4 | Tasks 1–2 closed state schema, digest, atomic writes, fail-closed load |
| 5–8 | Tasks 3–4 write-ahead checkpoints, recorded-terminal skip, in-flight re-execution exactly once, merged identity |
| 9–14 | Tasks 4–5 binding checks, retry contrast, cancel drain/checkpoint, `CANCELLED` domain outcome, resume of cancelled, replay fork |
| 15–17 | Tasks 4–6 one synthesis in the completing process, envelope/enum discipline, privacy in events and state |
| 18–20 | Tasks 3, 5–6 bounded-executor rules per phase, multi-phase language parity, offline cases, lower chain, clean-revision evidence |

All six Review Focus rows have named tests. Interfaces and wire names are consistent across tasks; internal language naming differs deliberately. The plan specifies signatures and behavioral assertions rather than implementation bodies. Crash control is a scripted fixture boundary (a real subprocess exit), not a runtime timeout/recovery feature. Future-file paths above are planned artifacts, not claims they already exist.

## Execution Ledger

- **Ruling 1 (2026-11-01):** The run-state `status` enum gains `PARTIAL` (and the result's `run_state_status` binds 1:1 to the result status), so a partially completed run's state document mirrors its terminal status exactly. This refines spec section 4's otherwise four-value enum; no other boundary changes. Recorded during Task 1 contract implementation.

## Execution Handoff

The owner approved this written plan and selected **Native** on 2026-11-01: implement the seven tasks in this session using `superpowers:executing-plans`, then obtain one fresh whole-branch review. These tasks share close interfaces and have no external business writes. Keep implementation within the accepted design and record any necessary ruling in the plan's execution ledger.





