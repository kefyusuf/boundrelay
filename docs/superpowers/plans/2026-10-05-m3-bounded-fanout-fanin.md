# M3 Bounded Fan-Out and Fan-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The owner selected Native execution on 2026-10-05.

**Goal:** Deliver the accepted offline order-brief lesson with three independent reads, sequential/parallel execution, explicit partial failure, deterministic synthesis, and exact-revision evidence.

**Architecture:** Keep each language implementation lesson-local. A fixed directory supplies workers; a bounded executor owns admission and validated outcomes; a collector restores canonical order; the runner calls one deterministic synthesizer after complete fan-in. Raw trace checks precede semantic projections. One M3 authority owns the M2→M1→M0 regression chain.

**Tech Stack:** Node.js >=24, Python >=3.14, TypeScript strict ESM, Vitest, tsx, Ajv/ajv-formats, PyYAML, jsonschema, unittest. Reuse M2's manifest/configuration patterns and pinned versions; no new orchestration dependency.

**Spec:** [Accepted M3 design](../specs/2026-10-05-m3-bounded-fanout-fanin-design.md), [D-014](../../decisions/D-014-m3-bounded-read-only-fanout-fanin.md).

**Status:** Written design and implementation plan accepted on 2026-10-05. The owner selected Native execution; implementation is in progress and not yet certified.

## Global Constraints

- Scenario `order-brief`; canonical input `ORD-1001`; order IDs match `^ORD-[0-9]{4}$`.
- Canonical worker order: `order-details`, `payment-status`, `delivery-status`. Exactly one invocation each; isolated immutable `{order_id}` input, no sibling outcomes or report reference.
- `sequential` has limit 1; `parallel` has limit 2. Hold a slot until its validated outcome is recorded. Declared failures release a slot and preserve queued work; no retries.
- Worker output fields are exactly `{order_id,order_status}`, `{order_id,payment_status}`, or `{order_id,delivery_status}`. Status enums are respectively `PROCESSING|SHIPPED|CANCELLED`, `PAID|UNPAID`, `PENDING|IN_TRANSIT|DELIVERED|DELAYED`; canonical values are `SHIPPED`, `PAID`, `DELAYED`.
- A worker outcome has exactly `worker_id`, `status`, `output`, `failure_code`. Success is `SUCCEEDED`, validated output, null failure; failure is `FAILED`, null output, `WORKER_EXECUTION_FAILED` or `INVALID_WORKER_OUTPUT`. Identity comes from admission, never returned payloads.
- Validate the original finite bounded JSON candidate before diagnostics/trace. Preserve M2's established depth limit 32 and safe integer range `[-(2**53-1), 2**53-1]` locally; reject cycles, non-finite numbers, wrong order IDs, extra/private fields, and malformed output without tracing their raw values. Oversized numeric/deep candidates are validation failures, not formatting exceptions.
- An unexpected implementation exception stops new admissions, drains already-entered finite workers, flushes the trace prefix, and exits CLI 2 without a canonical result. No runtime deadline, cancellation, retry, or invented domain outcome.
- With 3 successes: `SUCCEEDED`; with 1 or 2: `PARTIAL`; with 0: `FAILED` / `ALL_WORKERS_FAILED`. Overall failure is null otherwise. Synthesis is called once for any success, zero times for none.
- Brief fields: `order_id`, `sections` (successful `{worker_id,output}` entries), `missing_workers` (failed IDs), `complete`. Both arrays use canonical order. Only the synthesizer publishes the brief into the returned result.
- Result wire fields: `schema_version` (`1.0`), `run_id`, `scenario_id`, `case_id`, `execution_mode`, `concurrency_limit`, `peak_concurrency`, `order_id`, `status`, `worker_outcomes` (all three, canonical order), `synthesis_invoked`, `brief`, `failure_code`, `trace_path`.
- Keep the event envelope/version/types unchanged. Worker steps use `worker.<worker_id>`; synthesis uses `synthesize`. `run.completed` represents SUCCEEDED/PARTIAL; `run.failed` represents all-failed. Exactly one canonical terminal event.
- Exactly six canonical CLI cases and twelve language-specific traces. Extra adversarial tests and the naive teaching example are not new CLI modes/cases.
- Stay offline and framework-free. Exclude real models/providers, dynamic topology, Go, MCP, external business writes, retries, runtime deadlines/cancellation, persistence/recovery, and M4/M5 features.
- Publish evidence only on a clean unchanged candidate revision, after M2 and its lower chain pass on that same revision. Safety checks must survive `python -O`.

## Review Focus

| Failure/input class | Required evidence | Owner |
|---|---|---|
| Gate acknowledges raw completion before outcome recording, or waits for all three behind two slots | Controlled admission and acknowledgement tests; third cannot enter early | Tasks 2–3 |
| Fatal exception leaves a sibling gated forever or admits the queued worker | Independent finite drain test, no retry/canonical result, flushed prefix | Tasks 3, 5 |
| Cyclic/private/oversized output is sanitized into apparently valid facts | Original-candidate rejection plus trace privacy and two-failure assertions | Tasks 2, 4–5 |
| Parity projection hides duplicate worker events, wrong identity, early synthesis, or false peak | Raw-first mutation tests for every transition and result binding | Task 6 |
| Successful test process ran zero required probes; stale evidence or moved HEAD gets certified | Required passed-test identity checks and optimized-Python publication tests | Task 6 |

## File and Interface Map

Use `TS = lessons/03-parallel-fanout-fanin/typescript` and `PY = lessons/03-parallel-fanout-fanin/python`. All paths below are repository-relative; braces enumerate exact files. Python module prefix is `boundrelay_m3`.

| Files | Responsibility |
|---|---|
| `contracts/workers/order-brief-worker-result.schema.json`, `contracts/results/order-brief-result.schema.json` | Closed typed worker outcomes and run results |
| `fixtures/scenarios/order-brief.yaml`, `fixtures/workers/order-brief/{complete,partial-failure,all-failed,invalid-output}.yaml` | Six cases, finite outcomes, explicit completion schedules |
| `TS/src/{types,paths,schemas,scenario,workers,scripted-workers}.ts`; `PY/src/boundrelay_m3/{types,paths,schemas,scenario,workers,scripted_workers}.py` | Types, validation, input isolation, fixed directory, controlled fixtures |
| `TS/src/executor.ts`; `PY/src/boundrelay_m3/executor.py` | Bounded admission, validated outcomes, fatal drain |
| `TS/src/{collector,synthesizer}.ts`; Python equivalents | Complete fan-in, canonical order, brief construction |
| `TS/src/{trace,runner,cli}.ts`; Python equivalents and `__main__.py` | Event lifecycle, orchestration, CLI contract |
| `tools/parity/{verify_m3,test_m3_verification_safety}.py`, `scripts/verify_m3.py` | Raw checks, parity, gate, proof publication |
| `lessons/03-parallel-fanout-fanin/{README.md,invariants.yaml}`, `.github/workflows/m3.yml` | Teaching, invariant map, exact-head CI |

### Stable Interfaces

Define these in Task 2; subsequent tasks consume the same names and wire fields. Python uses snake_case methods/properties for internal APIs and the identical snake_case JSON wire fields.

- `WorkerId`: literal union of the three canonical IDs; `ExecutionMode`: `sequential|parallel`; `WorkerInput`: readonly `{order_id: string}` (Python frozen record). `WorkerOutput`, `WorkerOutcome`, `Brief`, `RunResult` follow Global Constraints. `CanonicalOutcomes` is a fixed three-outcome tuple in canonical order.
- `ValidationResult<T>`: `{valid:true,value:T}` or `{valid:false}`; Python equivalent frozen tagged result with `valid` and optional `value`, never raw rejected data. `validateWorkerOutput(workerId, raw, orderId)` / `validate_worker_output(...)` returns `ValidationResult<WorkerOutput>`.
- `WorkerExecutionError`: the only declared execution exception mapped to `WORKER_EXECUTION_FAILED`.
- `WorkerControl`: `acknowledgeOutcome(workerId): void` and `beginDrain(): void`; Python `acknowledge_outcome(worker_id)` and `begin_drain()`.
- `WorkerProvider` extends control: `read(workerId, input): Promise<unknown>`; Python `async read(worker_id, input) -> object`. `ScriptedWorkers` implements this protocol from validated fixture metadata. Unknown returned payloads remain unknown until runtime output validation.
- `WorkerDefinition`: `{id:WorkerId, handle:(input:WorkerInput)=>Promise<unknown>}`; Python frozen definition with async callable. `WorkerDirectory.resolve(id)` returns that definition or undefined/None. `createWorkerDirectory(provider)` / `create_worker_directory(provider)` closes over read only; no trace/report/control handle enters worker input.
- `WorkerLifecycle`: started `{kind:'started',worker_id,input}` or terminal `{kind:'terminal',outcome}`. `WorkerObserver` is a synchronous orchestrator callback receiving one lifecycle record.
- `ExecutorOptions`: `{mode,input,directory,control,observer}`. `ExecutionSummary`: completion-ordered `outcomes` and `peakConcurrency` (Python `peak_concurrency`). `executeWorkers(options): Promise<ExecutionSummary>` / `async execute_workers(options) -> ExecutionSummary` owns all admissions.
- `canonicalizeOutcomes(outcomes, orderId): CanonicalOutcomes` / `canonicalize_outcomes(...)` rejects missing/duplicate/unknown identities before sorting. `synthesizeBrief(orderId, outcomes): Brief` / `synthesize_brief(...)` requires at least one success.
- `RunOptions`: `{caseId,tracePath,directory?,control?,synthesizer?}`; Python snake_case keyword equivalents. Override directory/control must be supplied together; default uses the scenario's scripted provider. Runner fixes trace source to `typescript` or `python` respectively. `runCase(options): Promise<RunResult>` / `async run_case(...) -> RunResult`; injected synthesizer has the exact signature above.
- `TraceSink.emit(type,data): void`, `flush(): void`; lesson-local event context owns source/run IDs/sequence. `CaseSpec` holds case ID, mode, worker fixture path, and completion order; `loadScenario()` / `load_scenario()` returns the validated six-case scenario.

### Canonical Cases

Each success fixture returns the canonical values above. Both initial parallel workers must enter before any release. Provider releases only an entered worker, then waits for recorded-outcome acknowledgement before the next release.

| Case | Mode | Completion order | Injected difference | Result / peak |
|---|---|---|---|---|
| `sequential-complete` | sequential | order, payment, delivery | none | SUCCEEDED / 1 |
| `parallel-complete` | parallel | order, payment, delivery | none | SUCCEEDED / 2 |
| `parallel-out-of-order` | parallel | payment, delivery, order | none | SUCCEEDED / 2 |
| `parallel-partial-failure` | parallel | order, payment, delivery | delivery raises declared error | PARTIAL / 2 |
| `parallel-all-failed` | parallel | order, payment, delivery | all raise declared errors | FAILED / 2 |
| `parallel-invalid-output` | parallel | order, payment, delivery | payment returns unsupported status | PARTIAL / 2 |

Here order/payment/delivery abbreviate the full IDs, never fixture wire values.

## Commands and Working Directory

Use repository root as explicit cwd. On this Windows host use `.venv/Scripts/python.exe` for `python`, and `npm.cmd` for `npm`; CI uses its configured executables. Resolve subprocess executables through `shutil.which`, preserving the established Windows npm fix. Set `$env:PYTHONPATH='lessons/03-parallel-fanout-fanin/python/src'` before Python unit commands. Commands below use `python`/`npm` as portable notation.

- TS unit/type checks: `npm --prefix lessons/03-parallel-fanout-fanin/typescript test -- test/<file>.test.ts`; `npm --prefix lessons/03-parallel-fanout-fanin/typescript run typecheck`.
- Python unit checks: `python -m unittest discover -s lessons/03-parallel-fanout-fanin/python/tests -p test_<file>.py -v`.
- A RED step must fail on its named behavioral assertion or missing implementation, not missing packages or bad cwd. Establish dependencies first. After the task's GREEN steps, run its affected tests and TS typecheck, inspect the diff, stage only its files, and commit with the specified message. Run the complete clean-revision authority after Task 7; intermediate task checks do not certify M3.

## Task 1: Shared Contracts, Fixtures, and Invariant Catalog

**Files — Create:** both contract files and all five fixture paths from the map; `tools/contracts/test_m3_contracts.py`; `lessons/03-parallel-fanout-fanin/invariants.yaml`.

**Interfaces:** Produce JSON Schema draft/version conventions matching M2, exact result/outcome fields above, and YAML scenario `{schema_version:'1.0',scenario_id,order_id,cases}`. Each case has `{case_id,execution_mode,worker_fixture,completion_order}`. Worker fixture maps exactly the three IDs to `{operation:'return',output:<unknown>}` or `{operation:'raise',failure_code:'WORKER_EXECUTION_FAILED'}`. No extra operators or fixture fields. A return's raw output intentionally may be invalid.

- [ ] Write `test_six_cases_and_closed_worker_contract` and `test_result_status_count_policy` with these assertions:
  ```python
  self.assertEqual(len(scenario['cases']), 6)
  self.assertEqual(len({c['case_id'] for c in scenario['cases']}), 6)
  self.assertEqual(valid_success['output']['payment_status'], 'PAID')
  self.assertFalse(schema_accepts({**valid_success, 'private_note': 'secret'}))
  self.assertFalse(schema_accepts({**valid_success, 'failure_code': 'WORKER_EXECUTION_FAILED'}))
  self.assertFalse(result_accepts(partial_with_complete_true))
  self.assertFalse(result_accepts(all_failed_with_brief))
  ```
  Define the helper names inside this test module using Draft202012Validator and real schema files. Add wrong worker/output variants, wrong order ID, duplicate identities, missing sections/failures, and extra keys as negative candidates; schema handles structural branches, semantic tests handle cross-field equality not expressible in schema.
- [ ] Run `python -m unittest tools.contracts.test_m3_contracts -v`; expect RED on missing contracts/fixtures or candidate acceptance.
- [ ] Implement closed schemas, exact six cases, four reusable worker fixtures, and a twenty-entry invariant catalog keyed `M3-01` through `M3-20` mapped to spec section 14. The invalid fixture returns payment status `UNKNOWN`, rather than failing fixture parsing.
- [ ] Rerun the contract command; expect all tests PASS, including deliberately invalid fixture behavior and distinct result branches.
- [ ] Commit only Task 1 files: `feat: define M3 order brief contracts and fixtures`.

## Task 2: Language Foundations and Controlled Worker Provider

**Files — Create:** `TS/{package.json,package-lock.json,tsconfig.json,.nvmrc}`; six foundation TS source files in the map; `TS/test/{foundations,scenario,schemas,scripted-workers}.test.ts`; `PY/{pyproject.toml,requirements-dev.txt}`; `PY/src/boundrelay_m3/__init__.py`; six corresponding Python source files; `PY/tests/test_{foundations,scenario,schemas,scripted_workers}.py`.

**Interfaces:** Produce all Stable Interfaces except executor/collector/synthesizer/runner bodies. `loadScenario` validates fixed topology, unique six case IDs, operators, paths inside fixture root, and an exact completion-order permutation feasible under that mode's admission order. `ScriptedWorkers` coordinates entered bodies and acknowledgements; `beginDrain` releases only entered gates and bypasses normal acknowledgement waits during fatal cleanup.

- [ ] Scaffold M3 manifests from M2 with names `@boundrelay/lesson-03-typescript` and `boundrelay-m3`, no new dependencies. Install with `npm --prefix lessons/03-parallel-fanout-fanin/typescript install` and `python -m pip install -r lessons/03-parallel-fanout-fanin/python/requirements-dev.txt`. Commit the generated lockfile; follow existing strict TS settings. TS root resolves four parents from src; Python root uses module-path parents[5].
- [ ] Write paired foundation/loader/validator tests. `reject_original_invalid_output` asserts invalid for extra private data, `ORD-9999`, unsupported enum, NaN/infinity, cyclic object, and an oversized candidate; returned validation failure contains no raw payload. `reject_infeasible_schedule` rejects sequential payment-first, duplicate/unknown/missing IDs and parallel delivery-first; `invalid_return_reaches_runtime_validation` confirms UNKNOWN loads as raw return data.
- [ ] Write paired `release_requires_entry_and_recorded_ack` tests with controlled promises/events: no early release of delivery; after order completes raw read, payment remains gated until `acknowledgeOutcome('order-details')`; calling `beginDrain` allows entered payment to finish and never enters delivery. Use test-only watchdogs, no sleeps or all-three-start barrier.
- [ ] Run the four affected TS/Python test files; expect RED on missing foundation/provider behavior.
- [ ] Implement signatures and fixed grammar. Clone/freeze fresh worker inputs at admission; use a Python frozen input record. Keep unknown output separate from parsed fixture metadata. Validate whole candidates with bounded traversal before Ajv/jsonschema and never repair them into accepted output.
- [ ] Run all Task 2 tests plus typecheck; expect PASS with event-driven gating and successful imports from repository root.
- [ ] Commit only Task 2 files: `feat: add M3 isolated workers and deterministic fixtures`.

## Task 3: Bounded Executor and Independent Concurrency Probes

**Files — Create:** `TS/src/executor.ts`, `TS/test/executor.test.ts`, `PY/src/boundrelay_m3/executor.py`, `PY/tests/test_executor.py`.

**Interfaces:** Consume Task 2 directory/control/observer types; produce `executeWorkers` and `ExecutionSummary`. Keep a bounded active set, canonical pending queue, and completion-ordered validated outcomes. Notify terminal observer before acknowledgement/slot reuse. Do not launch all three then place a semaphore inside their bodies. Python automatic sibling cancellation must not replace finite drain.

- [ ] Write paired `parallel_calls_overlap_without_exceeding_two` and `sequential_never_overlaps`. Instrument the actual worker bodies independently of runtime counters. Assert body max active equals 2/1, initial parallel entry IDs equal order/payment, delivery has not entered, each count equals 1, and copied inputs equal only `{order_id:'ORD-1001'}`. Release payment; await delivery entry while order is still active. Record observer terminal before delivery entry. Verify mutation of one input cannot change another input or source input.
- [ ] Run executor tests in both languages; expect RED on missing executor or incorrect admission/ownership.
- [ ] Implement `executeWorkers(options)` / `execute_workers(options)` with limit selected only from mode (1 or 2), outcomes validated before terminal notification, and slot ownership through recording. Resolve directory IDs from fixed canonical queue. Unknown directory entries are tooling errors.
- [ ] Write paired `declared_failures_do_not_retry` and `unexpected_error_drains_without_admitting_queued_worker`. Declared exception becomes WORKER_EXECUTION_FAILED, malformed return INVALID_WORKER_OUTPUT, all three called once. Inject unexpected error while first two bodies are entered: beginDrain called once, sibling exits, delivery call count is 0, original exception propagates, no synthesized FAILED outcome for the fatal worker.
- [ ] Run executor tests; expect RED for fatal cleanup if not implemented. Implement stop-admission → beginDrain → await every already-entered task → propagate first unexpected error. Sibling errors are consumed during drain; no unhandled rejection/task warnings. Observer errors follow the same fatal path. Normal declared failure keeps admitting queued work.
- [ ] Run complete executor tests plus typecheck; expect PASS. Preserve the four exact probe test names above (Python `ExecutorTests.test_<name>`); Task 6 requires their actual passed identities.
- [ ] Commit only Task 3 files: `feat: bound M3 worker execution and drain fatal failures`.

## Task 4: Complete Fan-In and Deterministic Brief Synthesis

**Files — Create:** `TS/src/{collector,synthesizer}.ts`, `TS/test/synthesis.test.ts`, `PY/src/boundrelay_m3/{collector,synthesizer}.py`, `PY/tests/test_synthesis.py`.

**Interfaces:** Consume validated completion-ordered outcomes; produce `canonicalizeOutcomes` and `synthesizeBrief`. Collector validates exactly three distinct known outcomes and matching order IDs before sorting. Synthesizer consumes canonical tuples, returns immutable/copy-isolated brief, and rejects all-failed input (runner must not call it).

- [ ] Write `canonical_merge_ignores_completion_order` in both languages:
  ```typescript
  expect(canonicalizeOutcomes([delivery, payment, order], 'ORD-1001')).toEqual([order, payment, delivery]);
  expect(synthesizeBrief('ORD-1001', [order, payment, delivery]).sections.map(s => s.worker_id))
    .toEqual(['order-details', 'payment-status', 'delivery-status']);
  expect(synthesizeBrief('ORD-1001', [order, failedPayment, failedDelivery]).missing_workers)
    .toEqual(['payment-status', 'delivery-status']);
  expect(synthesizeBrief('ORD-1001', [order, failedPayment, failedDelivery]).complete).toBe(false);
  ```
  Define typed fixtures in the test. Add paired `reject_incomplete_or_duplicate_fanin` and `failed_reads_do_not_fabricate_sections`: reject missing, duplicate, unknown, wrong order and malformed typed outcomes; two failures yield only order section; all-failed synthesis raises.
- [ ] Run synthesis tests; expect RED on missing collector/synthesizer or unstable ordering.
- [ ] Implement exact signatures. Canonicalization never silently overwrites in a map; validate cardinality/membership first. Synthesis includes only validated successes and explicit failed IDs, without a new fact or external write.
- [ ] Rerun tests plus typecheck; expect PASS with equal briefs for all successful completion permutations and isolated returned values.
- [ ] Commit only Task 4 files: `feat: synthesize M3 briefs after complete canonical fan in`.

## Task 5: Runner, Trace Lifecycle, CLI, and Offline Guards

**Files — Create:** `TS/src/{trace,runner,cli}.ts`, `TS/test/{runner,cli,offline}.test.ts`, `TS/test/helpers/offline-runner.ts`; `PY/src/boundrelay_m3/{trace,runner,cli,__main__}.py`, `PY/tests/test_{runner,cli_trace,offline}.py`, `PY/tests/offline_runner.py`.

**Interfaces:** Consume executor/collector/synthesizer, produce `TraceSink` and `runCase`. CLI options exactly `--mode sequential|parallel --case <id> --trace <path>`, matching accepted spec section 4. Reject case-incompatible mode. Python module CLI `python -m boundrelay_m3`; TS package run script `tsx src/cli.ts`. Reject unknown/duplicate/positional or missing arguments before worker calls. Runtime source IDs follow existing TS/Python source conventions.

- [ ] Write paired `synthesis_waits_for_all_outcomes` with injected directory/control and synthesizer spy. Hold delivery gate while two outcomes settle; assert synthesis calls 0. Release delivery, assert 1 call with canonical outcomes; all-failed asserts 0. Verify SUCCEEDED/PARTIAL/FAILED policy including the extra two-failure unit case, synthesis flag, null brief on all failure, and canonical result order.
- [ ] Write paired `trace_rejects_raw_private_payload` and `fatal_run_flushes_prefix_without_result`. Assert invalid payment gets FAILED typed outcome without private/raw value, no invalid facts in brief, and unexpected error has CLI exit 2/no JSON result/no canonical terminal, but persisted valid trace prefix. Check worker terminal data includes only safe typed outcome.
- [ ] Run runner/CLI tests in both languages; expect RED on absent lifecycle/CLI behavior.
- [ ] Implement runner lifecycle: created/started context includes requested case/mode/order/limit; emit worker starts and terminal outcomes through observer; after complete collector fan-in emit synthesize start with all outcomes, completed with exact brief, then the single correct run terminal with actual status. Generate/validate full RunResult and flush. On fatal error flush prefix in cleanup and propagate; do not append ordinary all-failed terminal.
- [ ] Implement strict CLI parsing, one nonblank JSON stdout result and exit 0 for all domain outcomes. Tooling diagnostics use stderr/exit 2; ordinary domain failures keep result semantics.
- [ ] Write offline launch tests following M2's pre-import guard pattern: TS guard installed before dynamic runner import, Python guard before import and after event-loop initialization where Windows requires it. Prove a deliberately network-using import is blocked in a fresh process. Run all six cases with guards active; no API keys required.
- [ ] Run Task 5 tests plus typecheck; expect PASS for lifecycle counts, privacy, once/zero synthesis, argument rejection, fatal cleanup, and blocked import/network probes.
- [ ] Commit only Task 5 files: `feat: expose M3 offline runs and validated trace lifecycle`.

## Task 6: Raw-First Parity and Exact-Revision Verification Authority

**Files — Create:** `tools/parity/{verify_m3,test_m3_verification_safety}.py`, `scripts/verify_m3.py`. **Reuse without changing semantics:** `tools/parity/normalize.py`, lower milestone authorities and shared event schema.

**Interfaces:** `assert_case_behavior(result, events, case, trace_path, source) -> None` checks raw lifecycle/result bindings; `semantic_trace(result, events, case, trace_path, source) -> dict` calls raw assertion before projection; `business_projection(result) -> dict` uses an explicit field allowlist. `publish_evidence(evidence, starting_revision) -> None` rejects dirty/moved HEAD and mismatched lower proof before writing PASSED. `validate_probe_reports(ts_report, python_report) -> dict` demands the four passed executor names from Task 3 and nonzero suites.

- [ ] Write `test_raw_mutations_fail_before_projection`: mutate duplicate/missing start/terminal, worker identity, payload order ID, wrong source/run/context, noncontiguous sequence, duplicate event ID, blank/invalid JSONL, NaN, incorrect completion schedule, early synthesize, false peak/limit, mismatched brief, lost failure, false complete, duplicate terminal, or terminal status. Assert each raises before normalization; reject result/trace path mismatches. Use explicit exceptions in production verification, not removable `assert`.
- [ ] Run `python -m unittest tools.parity.test_m3_verification_safety -v`; expect RED on missing verifier/acceptance of mutations.
- [ ] Implement strict schema/payload validation plus an active-worker set reconstructed from raw starts/terminals. Check peak and slots, exact ordered per-worker lifecycle, complete fan-in before synthesis, once/zero synth, correct final terminal, and expected fixture completion order. Never collapse repeated step events into `by_type` maps.
- [ ] Implement same-case/mode language comparison: retain per-worker lifecycle records in their own order, observed completion order, synth/run lifecycle, exact semantic payloads and counts. Remove only generated metadata through existing normalizer; remove global sequence only inside worker records after raw validation. No global event sorting. Business comparison retains order_id/status/failure_code/worker_outcomes/synthesis_invoked/brief; only that projection drops case/mode/limit/peak/schedule/generated metadata. Compare sequential-complete, parallel-complete and parallel-out-of-order business equality.
- [ ] Write `test_missing_probe_or_zero_suite_cannot_certify`: absent/skipped/failed required test names, zero tests, malformed report and import-error discovery stub all reject. TS report requires `success=true`, positive numPassedTests, zero failed tests/suites, and each required assertion's `title` plus matching `fullName` in executor suite with `status='passed'`. Python uses discovered real ExecutorTests IDs and actual successful execution records, not mere discovery counts.
- [ ] Write `test_publication_checks_survive_optimization`: stale M3 evidence cleared before lower invocation; failed chain, lower evidence wrong SHA/status, moved HEAD or dirty tree cannot publish. Execute the targeted safety suite under `python -O` too. Run these tests RED before implementing report/evidence checks.
- [ ] Implement top gate: capture clean starting SHA; clear only `.boundrelay/m3`; invoke M2 once; validate M0/M1/M2 evidence exact SHA and PASSED; run shared contracts, TS typecheck/full tests with Vitest JSON reporter, full Python tests with a collecting unittest result, verifier safety and offline guards; require passed probe identities; run six paired CLIs; validate twelve raw traces, semantic parity, business equality; recheck clean HEAD and publish.
- [ ] Record command/runtime versions, revision, six case records, twelve raw paths, validated results, full test counts and required passed probe identities. Use `testResults[].assertionResults[].{title,fullName,status}` from installed Vitest JSON types; Python runner records each discovered test ID and success/failure, refuses zero/failed import suites. Never use `--passWithNoTests`.
- [ ] Run normal and optimized verifier-safety tests plus both complete language suites/typecheck; expect PASS. Full authority remains deferred until Task 7's complete committed candidate.
- [ ] Commit only Task 6 files: `test: certify M3 raw lifecycle parity and concurrency evidence`.

## Task 7: Teaching Demonstration, CI, and Candidate Certification

**Files — Create:** `lessons/03-parallel-fanout-fanin/README.md`, `.github/workflows/m3.yml`, `TS/test/naive-example.test.ts`, `PY/tests/test_naive_example.py`. **Modify:** root `README.md`, `.ai/delivery/current-scope.md`, M3 invariant catalog and this plan's completion checkboxes only when actually earned.

**Interfaces:** A test-local naive example is pedagogical, never imported by the CLI. CI runs `python scripts/verify_m3.py` on exact candidate SHA, Node24/Python3.14, same dependencies; uploads `m3-verification-<revision>` including hidden files. M2 remains implemented authority until the new authority actually passes.

- [ ] Write paired `naive_unbounded_reads_change_report_order`: controlled gates allow three entered bodies and naive shared append yields payment/delivery/order; canonical expected order is order/payment/delivery. The regression passes by demonstrating both violations, and compares the corrected executor's cap2/canonical synthesis. No sleep, benchmark, external call, or seventh case.
- [ ] Run naive example tests; expect RED before the isolated demonstration exists. Implement it only inside test modules and rerun; expect PASS proving the naive defects and corrected behavior.
- [ ] Write lesson README: known-ID problem → sequential baseline → justified overlap → naive failure → controlled worker failures → bounded correction → evidence. Include exact six-case CLI commands, outcome/brief examples, worker/controller ownership, deterministic scheduling rationale, partial/all-failed policies, fatal tooling boundary, invariants, and limits of local/CI evidence. Explain when sequential is enough; make no measured speedup claim.
- [ ] Add exact-head M3 workflow using current repository action versions (checkout/setup-node/setup-python/upload-artifact v7), `persist-credentials:false`, existing PR/main triggers, lower-chain dependencies, and hidden evidence upload. Never certify an uncommitted or synthetic merge tree as the PR head. Update root README and scope to point to M3 authority only with precise implementation status.
- [ ] Inspect scope/diff, run `git diff --check`, then commit Task 7 files: `docs: teach M3 fan out and enable revision bound CI`. Do not change M0/M1/M2 domain code or the global normalizer.
- [ ] On the clean committed candidate run `python scripts/verify_m3.py`; expect PASSED evidence on the exact starting/current SHA, lower cases 7/8/5, M3 cases6/traces12, nonzero full tests and all required independent probes passed. If any fix changes tracked files, commit it and rerun this authority on the new clean revision.
- [ ] Run one fresh whole-branch independent review using the chosen execution workflow, resolve material findings within accepted scope, and rerun only affected checks plus fresh full authority when a change invalidates evidence. Preserve trace privacy, drain behavior and raw-first proof as review priorities.
- [ ] Push the existing branch/update its draft PR description around final implemented behavior and validation. Check M0/M1/M2/M3 CI on the exact latest head and verify downloaded M3 artifact SHA/status/case counts. Mark ready only after required checks/review pass; merge/release require the owner's separate authorization.
- [ ] Append one completed-task activity entry and update project continuation state with actual SHA, PR/CI/evidence status, remaining blockers and the next bounded action. Never label unobserved CI or M3 production behavior as proved.

## Inline Self-Review and Coverage

Reviewed this plan against all spec sections and twenty invariants. Tasks 1–2 fix grammar/contracts/privacy/input ownership; Task 3 owns admissions, caps and failures; Task 4 owns complete canonical merge; Task 5 owns publication/trace/CLI/offline behavior; Task 6 owns raw validation/parity/probe proof/evidence; Task 7 owns the D-005 teaching sequence, CI and completion. No M3 product code is included in this planning change.

| Spec invariants | Implementation and evidence |
|---|---|
| 1–5 | Tasks 2–3 fixed queue, isolated input, body probes and gated admission |
| 6–9 | Tasks 2–5 closed outcomes, original-candidate privacy, declared failures, finite fatal drain |
| 10–15 | Tasks 4–5 complete fan-in, synthesis spy, canonical sections/missing facts, success-count policy, single publisher |
| 16–18 | Task 6 raw-first mutation suite, correct terminal, language and business projections |
| 19–20 | Tasks 1, 5–7 six offline cases, schemas, lower chain and clean revision evidence |

All five Review Focus rows have named tests. Interfaces and wire names are consistent across tasks; internal language naming differs deliberately. The plan specifies signatures and behavioral assertions rather than implementation bodies. Unexpected drain is a cleanup mechanism for finite scripted work, not a runtime cancellation/recovery feature. Future-file paths above are planned artifacts, not claims they already exist.

## Execution Handoff

The owner approved this written plan and selected **Native** on 2026-10-05: implement the seven tasks in this session using `superpowers:executing-plans`, then obtain one fresh whole-branch review. These tasks share close interfaces and have no external business writes. Keep implementation within the accepted design and record any necessary ruling in the plan's execution ledger.
